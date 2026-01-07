from django.db.models import Count, Sum, F, Avg, Q
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from django.utils import timezone
from datetime import timedelta
from apps.auth.models import User
from apps.organizations.models import Organization
from apps.usage.models import UsageEvent, Subscription, UpgradeInterest
from apps.payments.models import Invoice
from apps.sites.models import Site
from apps.chatbot.models import Chatbot
from apps.indexing.models import IndexingJob
from apps.chat.models import ChatSession, ChatMessage

class AdminStatsService:
    @staticmethod
    def get_overview_stats():
        """Get high-level stats for dashboard cards"""
        now = timezone.now()
        last_month = now - timedelta(days=30)
        last_week = now - timedelta(days=7)

        # User Stats
        total_users = User.objects.count()
        new_users_30d = User.objects.filter(created_at__gte=last_month).count()
        new_users_7d = User.objects.filter(created_at__gte=last_week).count()
        active_users_7d = User.objects.filter(last_login__gte=last_week).count()
        verified_users = User.objects.filter(is_email_verified=True).count()

        # Org Stats
        total_orgs = Organization.objects.count()
        orgs_by_tier = dict(
            Organization.objects.values('plan_tier')
            .annotate(count=Count('id'))
            .values_list('plan_tier', 'count')
        )

        # Site Stats
        total_sites = Site.objects.count()
        indexed_sites = Site.objects.exclude(last_indexed_at__isnull=True).count()

        # Chatbot Stats
        total_chatbots = Chatbot.objects.count()
        active_chatbots = Chatbot.objects.filter(status='active').count()

        # Indexing Job Stats
        total_jobs = IndexingJob.objects.count()
        jobs_last_24h = IndexingJob.objects.filter(created_at__gte=now - timedelta(hours=24)).count()
        running_jobs = IndexingJob.objects.filter(status='running').count()
        failed_jobs_24h = IndexingJob.objects.filter(
            status='failed',
            created_at__gte=now - timedelta(hours=24)
        ).count()

        # Chat Stats
        total_sessions = ChatSession.objects.count()
        sessions_30d = ChatSession.objects.filter(created_at__gte=last_month).count()
        total_messages = ChatMessage.objects.count()
        messages_30d = ChatMessage.objects.filter(created_at__gte=last_month).count()

        # Revenue Stats (from paid invoices in last 30 days)
        revenue_30d_cents = Invoice.objects.filter(
            status='paid',
            paid_at__gte=last_month
        ).aggregate(total=Sum('amount_paid'))['total'] or 0

        # Waitlist Stats
        waitlist_pending = UpgradeInterest.objects.filter(status='pending').count()
        waitlist_total = UpgradeInterest.objects.count()

        # Calculate growth percentages (simple MOM)
        prev_month_start = last_month - timedelta(days=30)
        new_users_prev_30d = User.objects.filter(
            created_at__gte=prev_month_start,
            created_at__lt=last_month
        ).count()

        user_growth_pct = 0
        if new_users_prev_30d > 0:
            user_growth_pct = ((new_users_30d - new_users_prev_30d) / new_users_prev_30d) * 100

        return {
            # User stats
            "total_users": total_users,
            "new_users_30d": new_users_30d,
            "new_users_7d": new_users_7d,
            "user_growth_pct": round(user_growth_pct, 1),
            "active_users_7d": active_users_7d,
            "verified_users": verified_users,
            # Organization stats
            "total_organizations": total_orgs,
            "orgs_by_tier": orgs_by_tier,
            # Site stats
            "total_sites": total_sites,
            "indexed_sites": indexed_sites,
            # Chatbot stats
            "total_chatbots": total_chatbots,
            "active_chatbots": active_chatbots,
            # Indexing job stats
            "total_jobs": total_jobs,
            "jobs_last_24h": jobs_last_24h,
            "running_jobs": running_jobs,
            "failed_jobs_24h": failed_jobs_24h,
            # Chat stats
            "total_sessions": total_sessions,
            "sessions_30d": sessions_30d,
            "total_messages": total_messages,
            "messages_30d": messages_30d,
            # Revenue
            "revenue_30d": revenue_30d_cents / 100,
            # Waitlist
            "waitlist_pending": waitlist_pending,
            "waitlist_total": waitlist_total,
        }

    @staticmethod
    def get_user_growth_chart(days=30):
        """Get daily user signups for chart"""
        start_date = timezone.now() - timedelta(days=days)
        
        data = User.objects.filter(created_at__gte=start_date)\
            .annotate(date=TruncDay('created_at'))\
            .values('date')\
            .annotate(count=Count('id'))\
            .order_by('date')
            
        # Format for Recharts (fill in missing days if needed in frontend or here)
        return [
            {"date": entry['date'].strftime('%Y-%m-%d'), "users": entry['count']}
            for entry in data
        ]

    @staticmethod
    def get_revenue_chart(months=12):
        """Get monthly revenue for chart"""
        start_date = timezone.now() - timedelta(days=months*30)
        
        data = Invoice.objects.filter(status='paid', paid_at__gte=start_date)\
            .annotate(month=TruncMonth('paid_at'))\
            .values('month')\
            .annotate(amount=Sum('amount_paid'))\
            .order_by('month')
            
        return [
            {"date": entry['month'].strftime('%Y-%m'), "revenue": entry['amount'] / 100}
            for entry in data
        ]

    @staticmethod
    def get_plan_distribution():
        """Get count of organizations by plan"""
        data = Subscription.objects.values('plan')\
            .annotate(count=Count('id'))\
            .order_by('-count')
            
        return [
            {"name": entry['plan'].title(), "value": entry['count']}
            for entry in data
        ]

    @staticmethod
    def get_usage_trends(days=30):
        """Get daily message volume"""
        start_date = timezone.now() - timedelta(days=days)

        data = UsageEvent.objects.filter(type='chat', occurred_at__gte=start_date)\
            .annotate(date=TruncDay('occurred_at'))\
            .values('date')\
            .annotate(count=Count('id'))\
            .order_by('date')

        return [
            {"date": entry['date'].strftime('%Y-%m-%d'), "messages": entry['count']}
            for entry in data
        ]

    @staticmethod
    def get_platform_analytics():
        """Get comprehensive platform analytics"""
        now = timezone.now()
        last_month = now - timedelta(days=30)
        last_week = now - timedelta(days=7)

        # Daily chat sessions for the last 30 days
        daily_sessions = (
            ChatSession.objects
            .filter(created_at__gte=last_month)
            .annotate(date=TruncDay('created_at'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )

        # Daily messages for the last 30 days
        daily_messages = (
            ChatMessage.objects
            .filter(created_at__gte=last_month)
            .annotate(date=TruncDay('created_at'))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )

        # Daily indexing jobs for the last 30 days
        daily_jobs = (
            IndexingJob.objects
            .filter(created_at__gte=last_month)
            .annotate(date=TruncDay('created_at'))
            .values('date')
            .annotate(
                count=Count('id'),
                completed=Count('id', filter=Q(status='completed')),
                failed=Count('id', filter=Q(status='failed'))
            )
            .order_by('date')
        )

        # Top organizations by usage
        top_orgs_by_sessions = (
            ChatSession.objects
            .filter(created_at__gte=last_month)
            .values('org_id')
            .annotate(session_count=Count('id'))
            .order_by('-session_count')[:10]
        )

        # Enrich with org details
        org_ids = [o['org_id'] for o in top_orgs_by_sessions if o['org_id']]
        org_details = {
            str(o.id): {'name': o.name, 'tier': o.plan_tier}
            for o in Organization.objects.filter(id__in=org_ids)
        }

        # Get message counts for these orgs
        message_counts = dict(
            ChatMessage.objects
            .filter(chat_session__org_id__in=org_ids, created_at__gte=last_month)
            .values('chat_session__org_id')
            .annotate(count=Count('id'))
            .values_list('chat_session__org_id', 'count')
        )

        # Get chatbot counts for these orgs
        site_ids_by_org = {}
        for site in Site.objects.filter(org_id__in=org_ids):
            if str(site.org_id) not in site_ids_by_org:
                site_ids_by_org[str(site.org_id)] = []
            site_ids_by_org[str(site.org_id)].append(site.id)

        chatbot_counts = {}
        for org_id, site_list in site_ids_by_org.items():
            chatbot_counts[org_id] = Chatbot.objects.filter(site_id__in=site_list).count()

        top_orgs = []
        for o in top_orgs_by_sessions:
            if not o['org_id']:
                continue
            org_id_str = str(o['org_id'])
            org_info = org_details.get(org_id_str, {})
            top_orgs.append({
                'id': org_id_str,
                'name': org_info.get('name', 'Unknown'),
                'tier': org_info.get('tier', 'basic'),
                'session_count': o['session_count'],
                'message_count': message_counts.get(o['org_id'], 0),
                'chatbot_count': chatbot_counts.get(org_id_str, 0),
            })

        return {
            'daily_sessions': [
                {'date': e['date'].strftime('%Y-%m-%d'), 'count': e['count']}
                for e in daily_sessions
            ],
            'daily_messages': [
                {'date': e['date'].strftime('%Y-%m-%d'), 'count': e['count']}
                for e in daily_messages
            ],
            'daily_jobs': [
                {
                    'date': e['date'].strftime('%Y-%m-%d'),
                    'count': e['count'],
                    'completed': e.get('completed', 0),
                    'failed': e.get('failed', 0)
                }
                for e in daily_jobs
            ],
            'top_organizations': top_orgs,
        }

    @staticmethod
    def get_tier_stats():
        """Get statistics by tier"""
        tiers = ['basic', 'premium', 'enterprise']
        stats = {}

        for tier in tiers:
            orgs = Organization.objects.filter(plan_tier=tier)
            org_ids = orgs.values_list('id', flat=True)

            # Get sites for these orgs
            sites = Site.objects.filter(org_id__in=org_ids)
            site_ids = sites.values_list('id', flat=True)

            # Get chatbots for these sites
            chatbots = Chatbot.objects.filter(site_id__in=site_ids)

            # Get sessions for these orgs
            sessions = ChatSession.objects.filter(org_id__in=org_ids)

            stats[tier] = {
                'organization_count': orgs.count(),
                'site_count': sites.count(),
                'chatbot_count': chatbots.count(),
                'session_count': sessions.count(),
                'active_chatbots': chatbots.filter(status='active').count(),
            }

        return stats
