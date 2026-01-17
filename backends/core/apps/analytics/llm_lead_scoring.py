"""
LLM-Powered Lead Scoring Service

Uses OpenAI GPT to analyze conversations and generate intelligent lead scores
with semantic understanding, entity extraction, and AI-generated summaries.

This is a more advanced alternative to the rule-based LeadScoringService.
"""

import json
import logging
from typing import Optional, Dict, Any, List
from datetime import timedelta
from django.utils import timezone
from django.conf import settings

from apps.chat.models import ChatSession, ChatMessage
from apps.analytics.models import LeadScore

logger = logging.getLogger(__name__)

# Try to import OpenAI
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI package not installed. LLM lead scoring will not be available.")


class LLMLeadScoringService:
    """
    Advanced lead scoring using LLM analysis.

    Features:
    - Semantic intent detection (understands context, not just keywords)
    - Entity extraction (company, role, team size, budget signals)
    - AI-generated conversation summaries
    - Buying stage classification
    - Sentiment and urgency analysis
    - Competitive mention detection
    """

    # Prompt for lead analysis
    LEAD_ANALYSIS_PROMPT = """You are an expert sales analyst. Analyze this chatbot conversation and extract lead intelligence.

CONVERSATION:
{conversation}

Analyze the conversation and return a JSON object with the following structure:
{{
    "intent_analysis": {{
        "primary_intent": "string (one of: purchase, demo_request, pricing_inquiry, support, information_seeking, integration, partnership, other)",
        "intent_confidence": 0-100,
        "buying_signals": ["list of specific buying signals detected"],
        "objections": ["list of objections or concerns raised"]
    }},
    "lead_quality": {{
        "score": 0-100,
        "priority": "hot|warm|cold",
        "reasoning": "brief explanation of score"
    }},
    "entity_extraction": {{
        "company_name": "string or null",
        "job_title": "string or null",
        "team_size": "string or null (e.g., '10-50', '100+')",
        "industry": "string or null",
        "budget_signals": "string or null (any budget-related mentions)",
        "timeline": "string or null (urgency/timeline mentions)",
        "use_case": "string or null"
    }},
    "conversation_analysis": {{
        "summary": "2-3 sentence summary of what the visitor wanted",
        "key_questions": ["top 3 most important questions asked"],
        "sentiment": "positive|neutral|negative",
        "urgency_level": "high|medium|low",
        "engagement_quality": "high|medium|low"
    }},
    "recommendations": {{
        "follow_up_action": "string (recommended next step)",
        "talking_points": ["key points for sales follow-up"],
        "content_gaps": ["topics where chatbot couldn't fully help"]
    }},
    "competitor_mentions": ["list of competitor names mentioned, if any"]
}}

Important:
- Be conservative with "hot" classification - only for clear purchase intent
- Score 70+ = hot, 40-69 = warm, below 40 = cold
- Extract entities only if explicitly mentioned
- Return valid JSON only, no markdown"""

    def __init__(self, api_key: str = None, model: str = None):
        """
        Initialize the LLM scoring service.

        Args:
            api_key: OpenAI API key (defaults to settings.OPENAI_API_KEY)
            model: Model to use (defaults to settings.LEAD_SCORING_LLM_MODEL)
        """
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI package is required. Install with: pip install openai")

        self.api_key = api_key or getattr(settings, 'OPENAI_API_KEY', None)
        if not self.api_key:
            raise ValueError("OpenAI API key not configured. Set OPENAI_API_KEY in settings.")

        self.client = OpenAI(api_key=self.api_key)
        self.model = model or getattr(settings, 'LEAD_SCORING_LLM_MODEL', 'gpt-4o-mini')

    def _format_conversation(self, messages: List[ChatMessage]) -> str:
        """Format messages into a readable conversation string."""
        formatted = []
        for msg in messages:
            role = "Visitor" if msg.role == "user" else "Chatbot"
            formatted.append(f"{role}: {msg.content}")
        return "\n".join(formatted)

    def _call_llm(self, conversation: str) -> Optional[Dict[str, Any]]:
        """Call the LLM API to analyze the conversation."""
        try:
            prompt = self.LEAD_ANALYSIS_PROMPT.format(conversation=conversation)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a sales intelligence analyst. Always respond with valid JSON only."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3,  # Lower temperature for more consistent analysis
                max_tokens=1500,
                response_format={"type": "json_object"}  # Force JSON response
            )

            result = response.choices[0].message.content
            return json.loads(result)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM API call failed: {e}", exc_info=True)
            return None

    def score_session(self, session: ChatSession) -> Optional[LeadScore]:
        """
        Score a session using LLM analysis.

        Args:
            session: ChatSession to analyze

        Returns:
            LeadScore instance or None if analysis failed
        """
        try:
            # Get messages
            messages = list(session.messages.all().order_by('created_at'))
            if not messages:
                logger.debug(f"Session {session.id} has no messages")
                return None

            user_messages = [m for m in messages if m.role == 'user']
            if not user_messages:
                logger.debug(f"Session {session.id} has no user messages")
                return None

            # Format conversation for LLM
            conversation = self._format_conversation(messages)

            # Analyze with LLM
            analysis = self._call_llm(conversation)
            if not analysis:
                logger.warning(f"LLM analysis failed for session {session.id}, falling back to rule-based")
                # Could fall back to rule-based scoring here
                return None

            # Extract data from analysis
            lead_quality = analysis.get('lead_quality', {})
            intent_analysis = analysis.get('intent_analysis', {})
            entity_extraction = analysis.get('entity_extraction', {})
            conv_analysis = analysis.get('conversation_analysis', {})
            recommendations = analysis.get('recommendations', {})

            # Calculate scores
            total_score = lead_quality.get('score', 0)
            priority = lead_quality.get('priority', 'cold')

            # Map priority if needed
            if priority not in ['hot', 'warm', 'cold']:
                if total_score >= 70:
                    priority = 'hot'
                elif total_score >= 40:
                    priority = 'warm'
                else:
                    priority = 'cold'

            # Calculate engagement and intent scores (for backwards compatibility)
            # Split total score roughly
            engagement_score = min(total_score // 2, 50)
            intent_score = total_score - engagement_score

            # Build geo location
            geo_parts = []
            if session.geo_city:
                geo_parts.append(session.geo_city)
            if session.geo_region:
                geo_parts.append(session.geo_region)
            if session.geo_country_name:
                geo_parts.append(session.geo_country_name)
            geo_location = ', '.join(geo_parts) if geo_parts else None

            # Calculate duration
            start = session.started_at or session.created_at
            end = session.ended_at or session.last_activity or timezone.now()
            duration_seconds = int((end - start).total_seconds()) if start and end else 0

            # Build enhanced summary
            summary_parts = []
            if conv_analysis.get('summary'):
                summary_parts.append(conv_analysis['summary'])
            if entity_extraction.get('company_name'):
                summary_parts.append(f"Company: {entity_extraction['company_name']}")
            if entity_extraction.get('use_case'):
                summary_parts.append(f"Use case: {entity_extraction['use_case']}")
            if recommendations.get('follow_up_action'):
                summary_parts.append(f"Action: {recommendations['follow_up_action']}")

            conversation_summary = ' | '.join(summary_parts) if summary_parts else ''

            # Build key questions from analysis
            key_questions = conv_analysis.get('key_questions', [])[:5]

            # Check feedback
            has_positive = any(m.feedback == 'like' for m in messages)
            has_negative = any(m.feedback == 'dislike' for m in messages)

            # Build comprehensive LLM insights object
            llm_insights = {
                'analyzed_by_llm': True,
                'model_used': self.model,
                'intent': {
                    'primary': intent_analysis.get('primary_intent'),
                    'confidence': intent_analysis.get('intent_confidence'),
                    'buying_signals': intent_analysis.get('buying_signals', []),
                    'objections': intent_analysis.get('objections', []),
                },
                'entities': entity_extraction,
                'sentiment': conv_analysis.get('sentiment'),
                'urgency': conv_analysis.get('urgency_level'),
                'engagement_quality': conv_analysis.get('engagement_quality'),
                'competitor_mentions': analysis.get('competitor_mentions', []),
                'recommendations': recommendations,
                'reasoning': lead_quality.get('reasoning', ''),
            }

            # Create or update lead score with LLM insights
            lead_score, created = LeadScore.objects.update_or_create(
                session=session,
                defaults={
                    'chatbot': session.chatbot,
                    'org_id': session.org_id or (session.site.org_id if session.site else None),
                    'engagement_score': engagement_score,
                    'intent_score': intent_score,
                    'total_score': total_score,
                    'priority': priority,
                    'detected_intent': intent_analysis.get('primary_intent'),
                    'key_questions': key_questions,
                    'conversation_summary': conversation_summary,
                    'source_url': session.referrer,
                    'geo_location': geo_location,
                    'device_type': session.device_type,
                    'session_date': session.started_at.date() if session.started_at else timezone.now().date(),
                    'session_duration_seconds': duration_seconds,
                    'message_count': len(messages),
                    'had_positive_feedback': has_positive,
                    'had_negative_feedback': has_negative,
                    'llm_insights': llm_insights,  # Store the LLM analysis
                }
            )

            logger.info(
                f"LLM scored session {session.id}: {priority} ({total_score}) - "
                f"Intent: {intent_analysis.get('primary_intent')}, "
                f"Company: {entity_extraction.get('company_name', 'Unknown')}"
            )

            return lead_score

        except Exception as e:
            logger.error(f"Error in LLM scoring for session {session.id}: {e}", exc_info=True)
            return None

    def score_sessions_batch(
        self,
        sessions: List[ChatSession],
        max_concurrent: int = 5
    ) -> List[LeadScore]:
        """
        Score multiple sessions. For cost efficiency, can be rate-limited.

        Args:
            sessions: List of sessions to score
            max_concurrent: Max sessions to process (for cost control)

        Returns:
            List of LeadScore instances
        """
        results = []

        # Limit batch size for cost control
        sessions_to_process = sessions[:max_concurrent] if max_concurrent else sessions

        for session in sessions_to_process:
            lead_score = self.score_session(session)
            if lead_score:
                results.append(lead_score)

        return results

    def estimate_cost(self, message_count: int) -> dict:
        """
        Estimate API cost for scoring sessions.

        Args:
            message_count: Average messages per session

        Returns:
            Cost estimate dict
        """
        # Rough token estimates
        avg_tokens_per_message = 50
        prompt_tokens = 500  # System prompt

        input_tokens = prompt_tokens + (message_count * avg_tokens_per_message)
        output_tokens = 800  # JSON response

        # Pricing (as of 2024, adjust as needed)
        if self.model == "gpt-4o-mini":
            input_cost = input_tokens * 0.00015 / 1000
            output_cost = output_tokens * 0.0006 / 1000
        elif self.model == "gpt-4o":
            input_cost = input_tokens * 0.005 / 1000
            output_cost = output_tokens * 0.015 / 1000
        else:
            input_cost = input_tokens * 0.001 / 1000
            output_cost = output_tokens * 0.002 / 1000

        total_cost = input_cost + output_cost

        return {
            'model': self.model,
            'estimated_input_tokens': input_tokens,
            'estimated_output_tokens': output_tokens,
            'cost_per_session': f"${total_cost:.4f}",
            'cost_per_1000_sessions': f"${total_cost * 1000:.2f}",
        }


class HybridLeadScoringService:
    """
    Hybrid approach: Use rule-based for initial scoring, LLM for high-value leads.

    This is more cost-effective:
    - All sessions get rule-based scoring (free)
    - Only warm/hot leads get LLM analysis (paid, but valuable)
    """

    def __init__(self, llm_threshold: int = None):
        """
        Args:
            llm_threshold: Minimum rule-based score to trigger LLM analysis
                          (defaults to settings.LEAD_SCORING_LLM_THRESHOLD)
        """
        from apps.analytics.services import LeadScoringService

        self.rule_based_service = LeadScoringService()
        self.llm_threshold = llm_threshold or getattr(settings, 'LEAD_SCORING_LLM_THRESHOLD', 25)
        self._llm_service = None

    @property
    def llm_service(self):
        """Lazy load LLM service."""
        if self._llm_service is None:
            try:
                self._llm_service = LLMLeadScoringService()
            except (ImportError, ValueError) as e:
                logger.warning(f"LLM service not available: {e}")
        return self._llm_service

    def score_session(self, session: ChatSession) -> Optional[LeadScore]:
        """
        Score a session using hybrid approach.

        1. First, do rule-based scoring
        2. If score >= threshold, enhance with LLM analysis
        """
        # Step 1: Rule-based scoring
        lead_score = self.rule_based_service.score_session(session)

        if not lead_score:
            return None

        # Step 2: If promising lead, enhance with LLM
        if lead_score.total_score >= self.llm_threshold and self.llm_service:
            try:
                # Get LLM analysis
                messages = list(session.messages.all().order_by('created_at'))
                if messages:
                    conversation = self.llm_service._format_conversation(messages)
                    analysis = self.llm_service._call_llm(conversation)

                    if analysis:
                        # Update lead score with LLM insights
                        lead_quality = analysis.get('lead_quality', {})
                        conv_analysis = analysis.get('conversation_analysis', {})
                        entity_extraction = analysis.get('entity_extraction', {})
                        intent_analysis = analysis.get('intent_analysis', {})

                        # Update score if LLM gives different assessment
                        llm_score = lead_quality.get('score', lead_score.total_score)

                        # Use higher of the two scores (benefit of doubt)
                        final_score = max(lead_score.total_score, llm_score)

                        # Update priority based on final score
                        if final_score >= 70:
                            priority = 'hot'
                        elif final_score >= 40:
                            priority = 'warm'
                        else:
                            priority = 'cold'

                        # Enhance summary with LLM insights
                        enhanced_summary = conv_analysis.get('summary', lead_score.conversation_summary)
                        if entity_extraction.get('company_name'):
                            enhanced_summary += f" | Company: {entity_extraction['company_name']}"

                        # Update the lead score
                        lead_score.total_score = final_score
                        lead_score.priority = priority
                        lead_score.conversation_summary = enhanced_summary
                        if intent_analysis.get('primary_intent'):
                            lead_score.detected_intent = intent_analysis['primary_intent']
                        if conv_analysis.get('key_questions'):
                            lead_score.key_questions = conv_analysis['key_questions'][:5]

                        lead_score.save()

                        logger.info(
                            f"Enhanced lead {session.id} with LLM: "
                            f"{lead_score.priority} ({lead_score.total_score})"
                        )

            except Exception as e:
                logger.error(f"LLM enhancement failed for session {session.id}: {e}")
                # Keep the rule-based score

        return lead_score

    def score_sessions_batch(self, sessions: List[ChatSession]) -> List[LeadScore]:
        """Score multiple sessions with hybrid approach."""
        results = []
        for session in sessions:
            lead_score = self.score_session(session)
            if lead_score:
                results.append(lead_score)
        return results
