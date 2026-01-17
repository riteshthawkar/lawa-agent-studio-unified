"""
Lead scoring service for analyzing chat sessions and identifying leads.

This service calculates lead scores based on:
- Engagement signals (message count, duration, feedback)
- Intent signals (pricing, demo, contact keywords)
- Conversation quality metrics
"""

import logging
from datetime import timedelta
from typing import Optional, List, Tuple
from django.utils import timezone
from django.db.models import Count, Avg

from apps.chat.models import ChatSession, ChatMessage
from apps.analytics.models import LeadScore

logger = logging.getLogger(__name__)


class LeadScoringService:
    """
    Service for scoring chat sessions to identify and prioritize leads.

    Scoring Components:
    - Engagement Score: Based on message count, duration, and feedback
    - Intent Score: Based on high-intent keywords in messages

    Priority Classification:
    - Hot: Total score >= 50
    - Warm: Total score >= 25
    - Cold: Total score < 25
    """

    # High-intent keywords grouped by category
    INTENT_KEYWORDS = {
        'pricing': {
            'keywords': ['pricing', 'price', 'cost', 'how much', 'quote', 'rates', 'fees', 'budget', 'affordable'],
            'score': 15,
        },
        'demo': {
            'keywords': ['demo', 'demonstration', 'trial', 'try', 'test', 'pilot', 'free trial', 'sandbox'],
            'score': 20,
        },
        'contact': {
            'keywords': ['contact', 'speak', 'call', 'meeting', 'schedule', 'talk to', 'representative', 'sales'],
            'score': 25,
        },
        'purchase': {
            'keywords': ['buy', 'purchase', 'subscribe', 'sign up', 'get started', 'order', 'upgrade'],
            'score': 30,
        },
        'enterprise': {
            'keywords': ['enterprise', 'team', 'business', 'company', 'organization', 'bulk', 'volume'],
            'score': 20,
        },
        'integration': {
            'keywords': ['integration', 'api', 'connect', 'webhook', 'zapier', 'automate'],
            'score': 15,
        },
        'support': {
            'keywords': ['help', 'support', 'issue', 'problem', 'bug', 'error', 'not working'],
            'score': 5,
        },
    }

    # Score thresholds for priority classification
    HOT_THRESHOLD = 50
    WARM_THRESHOLD = 25

    def score_session(self, session: ChatSession) -> Optional[LeadScore]:
        """
        Score a chat session and create/update a LeadScore record.

        Args:
            session: The ChatSession to score

        Returns:
            LeadScore instance or None if scoring failed
        """
        try:
            # Get all messages for the session
            messages = list(session.messages.all().order_by('created_at'))
            if not messages:
                logger.debug(f"Session {session.id} has no messages, skipping")
                return None

            user_messages = [m for m in messages if m.role == 'user']
            assistant_messages = [m for m in messages if m.role == 'assistant']

            # Calculate scores
            engagement_score = self._calculate_engagement_score(session, messages, user_messages)
            intent, intent_score = self._detect_intent(user_messages)
            total_score = engagement_score + intent_score

            # Determine priority
            priority = self._get_priority(total_score)

            # Extract additional context
            key_questions = self._extract_key_questions(user_messages)
            conversation_summary = self._generate_summary(user_messages, assistant_messages)
            duration_seconds = self._calculate_duration(session)
            feedback_info = self._analyze_feedback(messages)

            # Build geo location string
            geo_parts = []
            if session.geo_city:
                geo_parts.append(session.geo_city)
            if session.geo_region:
                geo_parts.append(session.geo_region)
            if session.geo_country_name:
                geo_parts.append(session.geo_country_name)
            geo_location = ', '.join(geo_parts) if geo_parts else None

            # Create or update lead score
            lead_score, created = LeadScore.objects.update_or_create(
                session=session,
                defaults={
                    'chatbot': session.chatbot,
                    'org_id': session.org_id or (session.site.org_id if session.site else None),
                    'engagement_score': engagement_score,
                    'intent_score': intent_score,
                    'total_score': total_score,
                    'priority': priority,
                    'detected_intent': intent,
                    'key_questions': key_questions,
                    'conversation_summary': conversation_summary,
                    'source_url': session.referrer,
                    'geo_location': geo_location,
                    'device_type': session.device_type,
                    'session_date': session.started_at.date() if session.started_at else timezone.now().date(),
                    'session_duration_seconds': duration_seconds,
                    'message_count': len(messages),
                    'had_positive_feedback': feedback_info['positive'],
                    'had_negative_feedback': feedback_info['negative'],
                }
            )

            action = "Created" if created else "Updated"
            logger.info(f"{action} lead score for session {session.id}: {priority} ({total_score})")
            return lead_score

        except Exception as e:
            logger.error(f"Error scoring session {session.id}: {e}", exc_info=True)
            return None

    def _calculate_engagement_score(
        self,
        session: ChatSession,
        messages: List[ChatMessage],
        user_messages: List[ChatMessage]
    ) -> int:
        """Calculate engagement score based on session metrics."""
        score = 0

        # Message count score (up to 20 points)
        # More messages = more engaged
        message_score = min(len(user_messages) * 3, 20)
        score += message_score

        # Duration score (up to 15 points)
        # Longer sessions indicate higher engagement
        duration_minutes = self._calculate_duration(session) / 60
        duration_score = min(int(duration_minutes * 2), 15)
        score += duration_score

        # Feedback score
        for msg in messages:
            if msg.feedback == 'like':
                score += 10  # Positive feedback is a strong signal
            elif msg.feedback == 'dislike':
                score -= 5  # Negative feedback reduces score slightly

        # Conversation depth (multi-turn conversations)
        # If user asked follow-up questions, they're more engaged
        if len(user_messages) >= 3:
            score += 5
        if len(user_messages) >= 5:
            score += 5

        # Citation interactions (if they clicked on sources)
        citations_count = sum(len(m.citations) for m in messages if m.role == 'assistant' and m.citations)
        if citations_count > 0:
            score += min(citations_count * 2, 10)

        return max(score, 0)  # Ensure non-negative

    def _detect_intent(self, user_messages: List[ChatMessage]) -> Tuple[Optional[str], int]:
        """
        Detect user intent from messages.

        Returns:
            Tuple of (intent_category, score)
        """
        if not user_messages:
            return None, 0

        # Combine all user messages
        all_text = ' '.join([m.content.lower() for m in user_messages])

        # Track intent scores
        intent_scores = {}

        for intent_category, config in self.INTENT_KEYWORDS.items():
            for keyword in config['keywords']:
                if keyword in all_text:
                    current_score = intent_scores.get(intent_category, 0)
                    intent_scores[intent_category] = current_score + config['score']

        if not intent_scores:
            return None, 0

        # Get the highest scoring intent
        top_intent = max(intent_scores, key=intent_scores.get)
        return top_intent, intent_scores[top_intent]

    def _get_priority(self, total_score: int) -> str:
        """Classify lead priority based on total score."""
        if total_score >= self.HOT_THRESHOLD:
            return 'hot'
        elif total_score >= self.WARM_THRESHOLD:
            return 'warm'
        else:
            return 'cold'

    def _extract_key_questions(self, user_messages: List[ChatMessage], limit: int = 5) -> List[str]:
        """Extract the most important questions from user messages."""
        questions = []

        for msg in user_messages:
            content = msg.content.strip()
            # Check if it's a question or contains high-intent keywords
            is_question = '?' in content or content.lower().startswith(('what', 'how', 'why', 'when', 'where', 'can', 'do', 'does', 'is', 'are'))

            # Check for high-intent content
            content_lower = content.lower()
            has_high_intent = any(
                kw in content_lower
                for category in self.INTENT_KEYWORDS.values()
                for kw in category['keywords']
            )

            if is_question or has_high_intent:
                # Truncate long messages
                if len(content) > 200:
                    content = content[:200] + '...'
                questions.append(content)

        return questions[:limit]

    def _generate_summary(
        self,
        user_messages: List[ChatMessage],
        assistant_messages: List[ChatMessage]
    ) -> str:
        """Generate a brief summary of the conversation."""
        if not user_messages:
            return ''

        # Get the first user message as the starting point
        first_message = user_messages[0].content[:100]
        summary_parts = [f"Started with: {first_message}"]

        # Detect topics discussed
        all_user_text = ' '.join([m.content.lower() for m in user_messages])
        topics = []
        for intent in self.INTENT_KEYWORDS:
            if any(kw in all_user_text for kw in self.INTENT_KEYWORDS[intent]['keywords']):
                topics.append(intent)

        if topics:
            summary_parts.append(f"Topics: {', '.join(topics)}")

        # Add message count
        summary_parts.append(f"{len(user_messages)} user messages, {len(assistant_messages)} bot responses")

        return ' | '.join(summary_parts)

    def _calculate_duration(self, session: ChatSession) -> int:
        """Calculate session duration in seconds."""
        start = session.started_at or session.created_at
        end = session.ended_at or session.last_activity or timezone.now()

        if start and end:
            duration = (end - start).total_seconds()
            return int(max(duration, 0))
        return 0

    def _analyze_feedback(self, messages: List[ChatMessage]) -> dict:
        """Analyze feedback across all messages."""
        return {
            'positive': any(m.feedback == 'like' for m in messages),
            'negative': any(m.feedback == 'dislike' for m in messages),
        }

    def score_sessions_batch(self, sessions: List[ChatSession]) -> List[LeadScore]:
        """
        Score multiple sessions in batch.

        Args:
            sessions: List of ChatSession instances to score

        Returns:
            List of created/updated LeadScore instances
        """
        results = []
        for session in sessions:
            lead_score = self.score_session(session)
            if lead_score:
                results.append(lead_score)
        return results

    def score_recent_sessions(self, hours: int = 24) -> List[LeadScore]:
        """
        Score all sessions from the last N hours.

        Args:
            hours: Number of hours to look back

        Returns:
            List of created/updated LeadScore instances
        """
        cutoff = timezone.now() - timedelta(hours=hours)
        sessions = ChatSession.objects.filter(
            started_at__gte=cutoff,
            status__in=['ended', 'timeout']
        ).select_related('chatbot', 'site').prefetch_related('messages')

        logger.info(f"Scoring {sessions.count()} sessions from the last {hours} hours")
        return self.score_sessions_batch(list(sessions))

    def rescore_all_sessions(self, org_id: str = None, days: int = 30) -> int:
        """
        Rescore all sessions for an organization (or all orgs) from the last N days.

        Args:
            org_id: Optional organization ID to filter by
            days: Number of days to look back

        Returns:
            Number of sessions scored
        """
        cutoff = timezone.now() - timedelta(days=days)
        sessions = ChatSession.objects.filter(
            started_at__gte=cutoff
        ).select_related('chatbot', 'site').prefetch_related('messages')

        if org_id:
            sessions = sessions.filter(org_id=org_id)

        count = sessions.count()
        logger.info(f"Rescoring {count} sessions from the last {days} days")

        self.score_sessions_batch(list(sessions))
        return count
