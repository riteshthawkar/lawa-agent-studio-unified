"""
Sentiment Analysis Service for Premium Analytics

Uses NLTK VADER for simple, efficient sentiment analysis without external API calls.
For production, could be upgraded to use OpenAI for more accurate analysis.
"""
import logging
from functools import lru_cache
from typing import Dict, List, Optional, Tuple
from django.db.models import Count, Avg, Q
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)

# Lazy load VADER to avoid import-time overhead
_vader_analyzer = None


def get_vader_analyzer():
    """Lazy load VADER sentiment analyzer"""
    global _vader_analyzer
    if _vader_analyzer is None:
        try:
            import nltk
            from nltk.sentiment.vader import SentimentIntensityAnalyzer
            
            # Download vader_lexicon if not present
            try:
                nltk.data.find('sentiment/vader_lexicon.zip')
            except LookupError:
                nltk.download('vader_lexicon', quiet=True)
            
            _vader_analyzer = SentimentIntensityAnalyzer()
            logger.info("VADER sentiment analyzer initialized")
        except Exception as e:
            logger.error(f"Failed to initialize VADER: {e}")
            _vader_analyzer = None
    return _vader_analyzer


def analyze_sentiment(text: str) -> Dict[str, float]:
    """
    Analyze sentiment of a text string using VADER.
    
    Returns:
        dict with keys: neg, neu, pos, compound
        compound is the overall sentiment score (-1 to 1)
    """
    analyzer = get_vader_analyzer()
    if not analyzer:
        return {'neg': 0, 'neu': 1, 'pos': 0, 'compound': 0}
    
    try:
        scores = analyzer.polarity_scores(text)
        return scores
    except Exception as e:
        logger.error(f"Sentiment analysis failed: {e}")
        return {'neg': 0, 'neu': 1, 'pos': 0, 'compound': 0}


def classify_sentiment(compound_score: float) -> str:
    """Classify compound score into categories"""
    if compound_score >= 0.05:
        return 'positive'
    elif compound_score <= -0.05:
        return 'negative'
    else:
        return 'neutral'


def analyze_query_sentiment(query: str) -> Tuple[str, float]:
    """
    Analyze a single user query and return classification and score.
    
    Returns:
        Tuple of (classification, compound_score)
    """
    scores = analyze_sentiment(query)
    compound = scores.get('compound', 0)
    classification = classify_sentiment(compound)
    return classification, compound


def get_sentiment_analytics(site_ids: List, days: int = 30, chatbot_id=None) -> Dict:
    """
    Get aggregate sentiment analytics for given sites/chatbots.
    
    Returns sentiment distribution, trends, and key insights.
    """
    from apps.chat.models import ChatMessage, ChatSession
    
    # Build date range
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    
    # Build base query for user messages
    messages_qs = ChatMessage.objects.filter(
        session__site_id__in=site_ids,
        role='user',
        created_at__gte=start_date,
        created_at__lte=end_date
    )
    
    if chatbot_id:
        messages_qs = messages_qs.filter(session__chatbot_id=chatbot_id)
    
    # Get sample of messages for sentiment analysis (limit for performance)
    sample_size = min(500, messages_qs.count())
    messages = list(messages_qs.order_by('-created_at')[:sample_size].values('content', 'created_at'))
    
    # Analyze sentiment for each message
    sentiments = {
        'positive': 0,
        'neutral': 0,
        'negative': 0,
    }
    total_compound = 0
    daily_sentiments = {}
    
    for msg in messages:
        classification, compound = analyze_query_sentiment(msg['content'])
        sentiments[classification] = sentiments.get(classification, 0) + 1
        total_compound += compound
        
        # Track daily sentiment
        date_key = msg['created_at'].strftime('%Y-%m-%d')
        if date_key not in daily_sentiments:
            daily_sentiments[date_key] = {'positive': 0, 'neutral': 0, 'negative': 0, 'total': 0, 'compound_sum': 0}
        daily_sentiments[date_key][classification] += 1
        daily_sentiments[date_key]['total'] += 1
        daily_sentiments[date_key]['compound_sum'] += compound
    
    total_messages = len(messages)
    avg_sentiment = total_compound / total_messages if total_messages > 0 else 0
    
    # Calculate percentages
    distribution = {
        'positive': round(sentiments['positive'] / total_messages * 100, 1) if total_messages else 0,
        'neutral': round(sentiments['neutral'] / total_messages * 100, 1) if total_messages else 0,
        'negative': round(sentiments['negative'] / total_messages * 100, 1) if total_messages else 0,
    }
    
    # Build daily trend
    trend = []
    for date_key in sorted(daily_sentiments.keys()):
        day_data = daily_sentiments[date_key]
        avg_daily = day_data['compound_sum'] / day_data['total'] if day_data['total'] else 0
        trend.append({
            'date': date_key,
            'avg_sentiment': round(avg_daily, 3),
            'positive': day_data['positive'],
            'neutral': day_data['neutral'],
            'negative': day_data['negative'],
            'total': day_data['total']
        })
    
    # Determine overall classification
    overall_classification = classify_sentiment(avg_sentiment)
    
    return {
        'summary': {
            'total_analyzed': total_messages,
            'avg_sentiment_score': round(avg_sentiment, 3),
            'overall_sentiment': overall_classification,
            'sample_size': sample_size,
        },
        'distribution': distribution,
        'counts': sentiments,
        'trend': trend,
        'insights': generate_sentiment_insights(sentiments, avg_sentiment, trend)
    }


def generate_sentiment_insights(sentiments: Dict, avg_sentiment: float, trend: List) -> List[Dict]:
    """Generate actionable insights from sentiment data"""
    insights = []
    
    total = sum(sentiments.values())
    if total == 0:
        return [{'type': 'info', 'message': 'Not enough data for sentiment analysis yet'}]
    
    positive_pct = sentiments['positive'] / total * 100
    negative_pct = sentiments['negative'] / total * 100
    
    # Overall sentiment insight
    if avg_sentiment > 0.2:
        insights.append({
            'type': 'positive',
            'title': 'Highly Positive Sentiment',
            'message': f'Users express predominantly positive sentiment ({positive_pct:.0f}% positive). Your chatbot is meeting user expectations well.'
        })
    elif avg_sentiment < -0.2:
        insights.append({
            'type': 'negative',
            'title': 'Concerning Sentiment Trend',
            'message': f'{negative_pct:.0f}% of queries express negative sentiment. Consider reviewing common pain points.'
        })
    else:
        insights.append({
            'type': 'neutral',
            'title': 'Neutral Sentiment Balance',
            'message': 'User sentiment is balanced. Most queries are informational in nature.'
        })
    
    # Trend analysis
    if len(trend) >= 7:
        recent = trend[-7:]
        older = trend[:-7] if len(trend) > 7 else []
        
        recent_avg = sum(d['avg_sentiment'] for d in recent) / len(recent)
        older_avg = sum(d['avg_sentiment'] for d in older) / len(older) if older else recent_avg
        
        if recent_avg > older_avg + 0.1:
            insights.append({
                'type': 'positive',
                'title': 'Improving Sentiment',
                'message': 'User sentiment has improved over the past week. Keep up the good work!'
            })
        elif recent_avg < older_avg - 0.1:
            insights.append({
                'type': 'warning',
                'title': 'Declining Sentiment',
                'message': 'Sentiment has declined recently. Consider checking for new issues.'
            })
    
    return insights


def get_cost_estimation(site_ids: List, days: int = 30, chatbot_id=None) -> Dict:
    """
    Estimate token costs based on usage data.
    
    Uses approximate pricing for common models.
    """
    from apps.chat.models import ChatMessage, ChatSession
    
    # Approximate pricing per 1K tokens (can be configured)
    PRICING = {
        'gpt-4o': {'input': 0.005, 'output': 0.015},
        'gpt-4o-mini': {'input': 0.00015, 'output': 0.0006},
        'gpt-4-turbo': {'input': 0.01, 'output': 0.03},
        'gpt-3.5-turbo': {'input': 0.0005, 'output': 0.0015},
        'default': {'input': 0.001, 'output': 0.003},  # Conservative estimate
    }
    
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    
    # Get token usage
    messages_qs = ChatMessage.objects.filter(
        session__site_id__in=site_ids,
        role='assistant',  # Count assistant responses for billing
        created_at__gte=start_date,
        created_at__lte=end_date
    )
    
    if chatbot_id:
        messages_qs = messages_qs.filter(session__chatbot_id=chatbot_id)
    
    # Aggregate tokens
    from django.db.models import Sum
    token_stats = messages_qs.aggregate(
        total_input=Sum('tokens_in'),
        total_output=Sum('tokens_out')
    )
    
    total_input = token_stats['total_input'] or 0
    total_output = token_stats['total_output'] or 0
    total_tokens = total_input + total_output
    
    # Calculate costs for different models
    pricing = PRICING['default']
    estimated_cost = (
        (total_input / 1000) * pricing['input'] +
        (total_output / 1000) * pricing['output']
    )
    
    # Daily breakdown
    from django.db.models.functions import TruncDate
    daily_usage = messages_qs.annotate(
        date=TruncDate('created_at')
    ).values('date').annotate(
        input_tokens=Sum('tokens_in'),
        output_tokens=Sum('tokens_out'),
        message_count=Count('id')
    ).order_by('date')
    
    daily_data = []
    for day in daily_usage:
        day_input = day['input_tokens'] or 0
        day_output = day['output_tokens'] or 0
        day_cost = (
            (day_input / 1000) * pricing['input'] +
            (day_output / 1000) * pricing['output']
        )
        daily_data.append({
            'date': day['date'].strftime('%Y-%m-%d') if day['date'] else None,
            'input_tokens': day_input,
            'output_tokens': day_output,
            'total_tokens': day_input + day_output,
            'messages': day['message_count'],
            'estimated_cost': round(day_cost, 4)
        })
    
    # Forecast (simple linear projection)
    avg_daily_cost = estimated_cost / days if days > 0 else 0
    monthly_forecast = avg_daily_cost * 30
    
    return {
        'summary': {
            'total_input_tokens': total_input,
            'total_output_tokens': total_output,
            'total_tokens': total_tokens,
            'estimated_cost': round(estimated_cost, 4),
            'currency': 'USD',
            'period_days': days,
        },
        'forecast': {
            'daily_average': round(avg_daily_cost, 4),
            'monthly_estimate': round(monthly_forecast, 2),
            'annual_estimate': round(monthly_forecast * 12, 2),
        },
        'daily_breakdown': daily_data,
        'pricing_model': 'default (GPT-4o-mini equivalent)',
    }


def get_retention_metrics(site_ids: List, days: int = 30, chatbot_id=None) -> Dict:
    """
    Calculate user retention and engagement metrics.
    """
    from apps.chat.models import ChatSession
    
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    
    sessions_qs = ChatSession.objects.filter(
        site_id__in=site_ids,
        started_at__gte=start_date,
        started_at__lte=end_date
    )
    
    if chatbot_id:
        sessions_qs = sessions_qs.filter(chatbot_id=chatbot_id)
    
    # Get unique session identifiers (client IP or session_key as proxy for user)
    from django.db.models.functions import TruncDate
    from django.db.models import Count, F, Avg, ExpressionWrapper, DurationField
    
    total_sessions = sessions_qs.count()
    
    # Sessions per day
    daily_sessions = sessions_qs.annotate(
        date=TruncDate('started_at')
    ).values('date').annotate(
        sessions=Count('id'),
        unique_ips=Count('client_ip', distinct=True)
    ).order_by('date')
    
    # Return user detection (same client_ip with sessions on different days)
    returning_users = sessions_qs.values('client_ip').annotate(
        session_days=Count(TruncDate('started_at'), distinct=True)
    ).filter(
        session_days__gt=1,
        client_ip__isnull=False
    ).count()
    
    unique_users = sessions_qs.values('client_ip').distinct().count()
    new_users = unique_users - returning_users
    
    # Session duration metrics
    duration_stats = sessions_qs.filter(
        ended_at__isnull=False
    ).annotate(
        duration=ExpressionWrapper(
            F('ended_at') - F('started_at'),
            output_field=DurationField()
        )
    ).aggregate(
        avg_duration=Avg('duration')
    )
    
    avg_duration_seconds = duration_stats['avg_duration'].total_seconds() if duration_stats['avg_duration'] else 0
    
    # Daily trend
    daily_data = []
    for day in daily_sessions:
        if day['date']:
            daily_data.append({
                'date': day['date'].strftime('%Y-%m-%d'),
                'sessions': day['sessions'],
                'unique_users': day['unique_ips'] or day['sessions']
            })
    
    return {
        'summary': {
            'total_sessions': total_sessions,
            'unique_users': unique_users,
            'returning_users': returning_users,
            'new_users': new_users,
            'return_rate': round(returning_users / unique_users * 100, 1) if unique_users else 0,
            'avg_session_duration_seconds': round(avg_duration_seconds, 0),
        },
        'daily_data': daily_data,
        'period_days': days,
    }
