"""
Celery tasks for analytics processing and report generation.

Tasks:
- score_recent_sessions: Daily task to score new sessions
- generate_weekly_reports: Weekly task to generate reports
- send_scheduled_reports: Hourly task to send scheduled emails
- score_session_async: Async task to score a single session
"""

import logging
from datetime import timedelta
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    ignore_result=True
)
def score_recent_sessions(self, hours: int = 24):
    """
    Score chat sessions from the last N hours.

    This task runs daily (recommended at 2 AM) to process
    all completed sessions and generate lead scores.

    Args:
        hours: Number of hours to look back (default 24)
    """
    from apps.analytics.services import LeadScoringService

    logger.info(f"Starting lead scoring for sessions from last {hours} hours")

    try:
        service = LeadScoringService()
        results = service.score_recent_sessions(hours=hours)
        logger.info(f"Successfully scored {len(results)} sessions")
        return {'scored': len(results)}

    except Exception as e:
        logger.error(f"Error in score_recent_sessions task: {e}", exc_info=True)
        raise


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    ignore_result=True
)
def generate_weekly_reports(self):
    """
    Generate weekly leads reports for all users with reports enabled.

    This task runs every Monday at 8 AM to generate reports
    for the previous week (Monday to Sunday).
    """
    from apps.analytics.report_service import WeeklyReportService

    logger.info("Starting weekly report generation")

    try:
        service = WeeklyReportService()
        count = service.generate_reports_for_all_users()
        logger.info(f"Generated {count} weekly reports")
        return {'reports_generated': count}

    except Exception as e:
        logger.error(f"Error in generate_weekly_reports task: {e}", exc_info=True)
        raise


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    ignore_result=True
)
def send_scheduled_reports(self):
    """
    Send report emails to users scheduled for the current hour.

    This task runs every hour to check for users who should
    receive their weekly report at this time.
    """
    from apps.analytics.email_service import ReportEmailService

    now = timezone.now()
    day_of_week = now.weekday()  # 0=Monday
    hour = now.hour

    logger.info(f"Checking for scheduled reports: day={day_of_week}, hour={hour}")

    try:
        service = ReportEmailService()
        sent_count = service.send_reports_for_day(day_of_week, hour)
        logger.info(f"Sent {sent_count} scheduled report emails")
        return {'emails_sent': sent_count}

    except Exception as e:
        logger.error(f"Error in send_scheduled_reports task: {e}", exc_info=True)
        raise


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    ignore_result=True
)
def score_session_async(self, session_id: str, use_llm: bool = None):
    """
    Score a single session asynchronously.

    Called when a session ends to immediately generate a lead score.

    Args:
        session_id: UUID of the session to score
        use_llm: Whether to use LLM scoring (None = use settings default)
    """
    from django.conf import settings
    from apps.chat.models import ChatSession
    from apps.analytics.services import LeadScoringService

    logger.debug(f"Scoring session {session_id}")

    # Determine scoring mode from settings if not specified
    if use_llm is None:
        use_llm = getattr(settings, 'LEAD_SCORING_USE_LLM', False)

    try:
        session = ChatSession.objects.select_related(
            'chatbot', 'site'
        ).prefetch_related('messages').get(id=session_id)

        # Choose scoring service
        if use_llm:
            try:
                from apps.analytics.llm_lead_scoring import HybridLeadScoringService
                service = HybridLeadScoringService()
                logger.debug(f"Using hybrid LLM scoring for session {session_id}")
            except (ImportError, ValueError) as e:
                logger.warning(f"LLM scoring not available, falling back to rule-based: {e}")
                service = LeadScoringService()
        else:
            service = LeadScoringService()

        lead_score = service.score_session(session)

        if lead_score:
            logger.info(f"Session {session_id} scored: {lead_score.priority} ({lead_score.total_score})")

            # Check for hot lead notification
            if lead_score.priority == 'hot':
                notify_hot_lead.delay(str(lead_score.id))

        return {'session_id': session_id, 'scored': lead_score is not None}

    except ChatSession.DoesNotExist:
        logger.warning(f"Session {session_id} not found for scoring")
        return {'session_id': session_id, 'error': 'Session not found'}

    except Exception as e:
        logger.error(f"Error scoring session {session_id}: {e}", exc_info=True)
        raise


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    ignore_result=True
)
def enhance_lead_with_llm(self, lead_score_id: str):
    """
    Enhance an existing lead score with LLM analysis.

    Use this to upgrade promising leads with deeper AI analysis.

    Args:
        lead_score_id: UUID of the LeadScore to enhance
    """
    from apps.analytics.models import LeadScore

    logger.info(f"Enhancing lead {lead_score_id} with LLM analysis")

    try:
        from apps.analytics.llm_lead_scoring import LLMLeadScoringService

        lead_score = LeadScore.objects.select_related(
            'session', 'chatbot'
        ).get(id=lead_score_id)

        service = LLMLeadScoringService()
        enhanced = service.score_session(lead_score.session)

        if enhanced:
            logger.info(f"Lead {lead_score_id} enhanced: {enhanced.priority} ({enhanced.total_score})")
            return {'lead_id': lead_score_id, 'enhanced': True, 'new_score': enhanced.total_score}
        else:
            return {'lead_id': lead_score_id, 'enhanced': False}

    except ImportError:
        logger.error("OpenAI package not installed for LLM scoring")
        return {'lead_id': lead_score_id, 'error': 'LLM not available'}

    except ValueError as e:
        logger.error(f"LLM configuration error: {e}")
        return {'lead_id': lead_score_id, 'error': str(e)}

    except LeadScore.DoesNotExist:
        logger.warning(f"LeadScore {lead_score_id} not found")
        return {'lead_id': lead_score_id, 'error': 'LeadScore not found'}

    except Exception as e:
        logger.error(f"Error enhancing lead {lead_score_id}: {e}", exc_info=True)
        raise


@shared_task(
    bind=True,
    max_retries=1,
    ignore_result=True
)
def batch_enhance_warm_leads_with_llm(self, org_id: str = None, days: int = 7, limit: int = 50):
    """
    Batch enhance warm leads with LLM analysis.

    Useful for periodic enhancement of promising leads that haven't been LLM-analyzed yet.

    Args:
        org_id: Optional organization filter
        days: Look back period
        limit: Max leads to process (for cost control)
    """
    from django.conf import settings
    from apps.analytics.models import LeadScore

    # Check if LLM scoring is enabled
    if not getattr(settings, 'LEAD_SCORING_USE_LLM', False):
        logger.debug("LLM lead scoring is disabled, skipping batch enhancement")
        return {'skipped': True, 'reason': 'LLM scoring disabled'}

    logger.info(f"Batch enhancing warm leads with LLM (org={org_id}, days={days}, limit={limit})")

    try:
        from apps.analytics.llm_lead_scoring import LLMLeadScoringService

        cutoff = timezone.now().date() - timedelta(days=days)

        # Get warm leads that might be worth enhancing
        leads_qs = LeadScore.objects.filter(
            session_date__gte=cutoff,
            priority='warm',
            total_score__gte=30  # Only reasonably scored leads
        ).select_related('session', 'chatbot')

        if org_id:
            leads_qs = leads_qs.filter(org_id=org_id)

        leads = list(leads_qs.order_by('-total_score')[:limit])

        if not leads:
            logger.info("No warm leads to enhance")
            return {'enhanced': 0}

        service = LLMLeadScoringService()
        enhanced_count = 0

        for lead in leads:
            try:
                result = service.score_session(lead.session)
                if result:
                    enhanced_count += 1
                    # If LLM upgraded to hot, send notification
                    if result.priority == 'hot' and lead.priority != 'hot':
                        notify_hot_lead.delay(str(result.id))
            except Exception as e:
                logger.error(f"Failed to enhance lead {lead.id}: {e}")
                continue

        logger.info(f"Enhanced {enhanced_count}/{len(leads)} leads with LLM")
        return {'enhanced': enhanced_count, 'total_processed': len(leads)}

    except ImportError:
        logger.error("OpenAI package not installed")
        return {'error': 'LLM not available'}

    except Exception as e:
        logger.error(f"Error in batch LLM enhancement: {e}", exc_info=True)
        raise


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
    ignore_result=True
)
def notify_hot_lead(self, lead_score_id: str):
    """
    Send immediate notification for a hot lead.

    Args:
        lead_score_id: UUID of the LeadScore
    """
    from apps.analytics.models import LeadScore, ReportPreferences
    from apps.analytics.email_service import ReportEmailService

    logger.info(f"Checking hot lead notification for {lead_score_id}")

    try:
        lead_score = LeadScore.objects.select_related('chatbot').get(id=lead_score_id)

        # Find users who want immediate hot lead notifications
        preferences = ReportPreferences.objects.filter(
            org_id=lead_score.org_id,
            notify_hot_leads_immediately=True
        ).select_related('user')

        if not preferences.exists():
            logger.debug(f"No users have hot lead notifications enabled for org {lead_score.org_id}")
            return {'lead_id': lead_score_id, 'notifications_sent': 0}

        service = ReportEmailService()
        sent_count = 0

        for pref in preferences:
            # Check if this chatbot is included in user's preferences
            if pref.include_chatbot_ids and str(lead_score.chatbot_id) not in pref.include_chatbot_ids:
                continue

            if service.send_hot_lead_notification(pref.user, lead_score):
                sent_count += 1

        logger.info(f"Sent {sent_count} hot lead notifications for lead {lead_score_id}")
        return {'lead_id': lead_score_id, 'notifications_sent': sent_count}

    except LeadScore.DoesNotExist:
        logger.warning(f"LeadScore {lead_score_id} not found")
        return {'lead_id': lead_score_id, 'error': 'LeadScore not found'}

    except Exception as e:
        logger.error(f"Error sending hot lead notification: {e}", exc_info=True)
        raise


@shared_task(
    bind=True,
    ignore_result=True
)
def rescore_organization_sessions(self, org_id: str, days: int = 30):
    """
    Rescore all sessions for an organization.

    Useful for recalculating scores after changing scoring logic.

    Args:
        org_id: Organization UUID
        days: Number of days to look back
    """
    from apps.analytics.services import LeadScoringService

    logger.info(f"Rescoring sessions for org {org_id}, last {days} days")

    try:
        service = LeadScoringService()
        count = service.rescore_all_sessions(org_id=org_id, days=days)
        logger.info(f"Rescored {count} sessions for org {org_id}")
        return {'org_id': org_id, 'sessions_rescored': count}

    except Exception as e:
        logger.error(f"Error rescoring org sessions: {e}", exc_info=True)
        raise


@shared_task(
    bind=True,
    ignore_result=True
)
def cleanup_old_lead_scores(self, days: int = 365):
    """
    Clean up lead scores older than N days.

    Args:
        days: Number of days to retain (default 365)
    """
    from apps.analytics.models import LeadScore

    cutoff = timezone.now().date() - timedelta(days=days)

    logger.info(f"Cleaning up lead scores older than {cutoff}")

    try:
        deleted, _ = LeadScore.objects.filter(session_date__lt=cutoff).delete()
        logger.info(f"Deleted {deleted} old lead scores")
        return {'deleted': deleted}

    except Exception as e:
        logger.error(f"Error cleaning up old lead scores: {e}", exc_info=True)
        raise
