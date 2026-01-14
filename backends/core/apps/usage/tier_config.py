"""
Tier-based feature configuration for analytics and platform features.

Tier Structure:
- basic: Free tier for all users
- premium: Paid tier with enhanced features
- enterprise: Custom tier with contact us option

Defines what features are available at each subscription tier.
"""

# Tier features and limits configuration
TIER_FEATURES = {
    'basic': {
        # Free tier - default for all new users
        'name': 'Basic',
        'price': 0,
        'price_display': 'Free',
        'description': 'Perfect for getting started',
        'max_days': 7,  # Analytics retention
        'top_queries_limit': 5,
        'export_formats': [],
        'features': [
            'core_stats',
            'daily_chart',
            'smart_insights_basic',
        ],
        'limits': {
            'sites': 1,
            'chatbots': 1,
            'daily_conversations': 100,
            'max_conversations': 5000,
            'pages_per_site': 50,
        }
    },
    'premium': {
        # Paid tier with enhanced features
        'name': 'Premium',
        'price': 4900,  # $49.00/month (placeholder - to be decided)
        'price_display': '$49/mo',
        'description': 'For growing businesses',
        'max_days': 90,  # Analytics retention
        'top_queries_limit': -1,  # Unlimited
        'export_formats': ['json', 'csv'],
        'features': [
            'core_stats',
            'daily_chart',
            'hourly_weekly_charts',
            'smart_insights_advanced',
            'query_categories',
            'query_search',
            'citation_analytics_unlimited',
            'citation_click_tracking',
            'geo_analytics_region',
            'feedback_list_view',
            'feedback_export',
            'feedback_drilldown',
            'token_usage_daily',
            'token_cost_estimation',
            'response_time_percentiles',
            'conversation_flow_avg',
            'retention_metrics',
            'sentiment_analysis_aggregate',
            'scheduled_reports_weekly',
            'api_access_readonly',
            'priority_support',
        ],
        'limits': {
            'sites': 10,
            'chatbots': 25,
            'daily_conversations': 1000,
            'max_conversations': -1,  # Unlimited
            'pages_per_site': 500,
        }
    },
    'enterprise': {
        # Custom tier - contact us
        'name': 'Enterprise',
        'price': None,  # Custom pricing
        'price_display': 'Contact Us',
        'description': 'For large organizations',
        'max_days': 365,  # Analytics retention
        'top_queries_limit': -1,  # Unlimited
        'export_formats': ['json', 'csv', 'pdf'],
        'features': [
            # All premium features plus:
            'all_premium_features',
            'geo_analytics_city',
            'geo_heatmap',
            'sentiment_analysis_per_message',
            'sentiment_trends',
            'user_journey_mapping',
            'conversation_flow_visualization',
            'cohort_analysis_weekly',
            'cohort_retention_tracking',
            'predictive_analytics_churn',
            'predictive_analytics_peaks',
            'capacity_forecasting',
            'realtime_dashboard',
            'peak_usage_alerts',
            'ab_testing_analytics',
            'custom_dashboards',
            'api_access_full',
            'scheduled_reports_daily',
            'scheduled_reports_custom',
            'whitelabel_reports_pdf',
            'dedicated_support',
            'sla_guarantee',
            'custom_integrations',
        ],
        'limits': {
            'sites': -1,  # Unlimited
            'chatbots': -1,  # Unlimited
            'daily_conversations': -1,  # Unlimited
            'max_conversations': -1,  # Unlimited
            'pages_per_site': -1,  # Unlimited
        }
    }
}


def get_tier_features(plan: str) -> dict:
    """Get features for a specific tier"""
    return TIER_FEATURES.get(plan, TIER_FEATURES['basic'])


def get_tier_limits(plan: str) -> dict:
    """Get limits for a specific tier"""
    return get_tier_features(plan).get('limits', TIER_FEATURES['basic']['limits'])


def has_feature(plan: str, feature_name: str) -> bool:
    """Check if a plan has access to a specific feature"""
    tier = get_tier_features(plan)

    # Enterprise has all premium features automatically
    if plan == 'enterprise':
        if feature_name in TIER_FEATURES['premium']['features']:
            return True

    return feature_name in tier.get('features', [])


def get_analytics_retention_days(plan: str, override: int = None) -> int:
    """Get analytics data retention days for a plan"""
    if override is not None:
        return override
    return get_tier_features(plan).get('max_days', 7)


def get_export_formats(plan: str) -> list:
    """Get available export formats for a plan"""
    return get_tier_features(plan).get('export_formats', [])


def get_query_limit(plan: str) -> int:
    """Get top queries limit for a plan (-1 means unlimited)"""
    return get_tier_features(plan).get('top_queries_limit', 5)


def is_unlimited(value: int) -> bool:
    """Check if a limit value represents unlimited (-1 or None)"""
    return value is None or value == -1


def format_limit(value: int) -> str:
    """Format a limit value for display"""
    if is_unlimited(value):
        return "Unlimited"
    return f"{value:,}"
