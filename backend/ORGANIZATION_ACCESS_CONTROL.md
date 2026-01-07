# Organization-Based Access Control Implementation

This document describes the multi-tenant organization-based access control system implemented across the platform.

## Overview

The system ensures that users can only access resources (sites, chatbots, indexing jobs, chat sessions) that belong to their organization(s). This is implemented through middleware, permission utilities, and consistent filtering in all views.

## Architecture

### 1. Middleware (`apps/core/middleware.py`)

**OrganizationMiddleware** automatically sets `request.org_id` from multiple sources (in order of precedence):

1. **JWT Token** - `org_id` claim in the access token
2. **API Key** - Organization associated with the API key (via `X-API-Key` header)
3. **URL Parameter** - `?org_id=<uuid>` query parameter
4. **User's Primary Organization** - First active organization the authenticated user belongs to (fallback)

The middleware also validates that the user has access to the specified organization, returning a 403 error if access is denied.

### 2. Permission Utilities (`apps/core/organization_permissions.py`)

#### Helper Functions

- **`get_user_organizations(user)`** - Returns all organizations the user is a member of
- **`check_organization_access(user, org_id)`** - Validates user has access to the organization
- **`check_site_access(user, site_id, org_id=None)`** - Validates user has access to a site
- **`check_chatbot_access(user, chatbot_id, org_id=None)`** - Validates user has access to a chatbot
- **`check_session_access(user, session_id, org_id=None)`** - Validates user has access to a chat session

#### Permission Classes (for DRF class-based views)

- **`IsOrganizationMember`** - Checks if user is a member of the organization
- **`IsSiteOwner`** - Checks if user owns the site through their organization
- **`IsChatbotOwner`** - Checks if user owns the chatbot through their organization
- **`IsSessionOwner`** - Checks if user owns the chat session through their organization

#### Decorators (for function-based views)

- **`@require_organization_access(org_param='org_id')`** - Requires organization access
- **`@require_site_access(site_param='site_id')`** - Requires site access

#### Custom Exceptions

- **`OrganizationAccessError`** - Raised when user doesn't have access to the organization
- **`ResourceNotInOrganizationError`** - Raised when a resource doesn't belong to user's organization

### 3. Views Implementation

All views in `apps/frontend/views.py` and `apps/frontend/management_views.py` implement organization-based filtering:

#### List Views (views.py)

- **`dashboard_stats`** - Filters all statistics by user's organizations
- **`sites_management`** - Filters sites by `org_id__in=org_ids`
- **`indexing_jobs_management`** - Filters jobs by `org_id__in=org_ids`
- **`chatbots_management`** - Filters through `site_id__in=user_site_ids` where sites belong to user's orgs
- **`user_profile`** - Filters activity summary by user's organizations
- **`bulk_actions`** - Validates all resource IDs belong to user's organizations before applying actions

#### Detail Views (views.py)

- **`site_detail`** - Uses `check_site_access()` to validate access

#### Management Views (management_views.py)

All management views use `org_id = getattr(request, 'org_id', None)` (set by middleware) to filter queries:

- **`create_site`** - Sets `org_id` on new sites
- **`update_site`** - Filters by `org_id` when looking up site
- **`delete_site`** - Filters by `org_id` when looking up site
- **`create_indexing_job`** - Filters site lookup by `org_id`
- **`create_chatbot`** - Filters site lookup by `org_id`
- **`get_or_update_chatbot`** - Filters through `site_id__in=org_site_ids`
- **`delete_chatbot`** - Filters through `site_id__in=org_site_ids`

### 4. Data Model

#### Organization Fields

- **Site** - `org_id` (UUIDField, nullable) - Organization owning the site
- **IndexingJob** - `org_id` (UUIDField, nullable) - Organization context for the job
- **Chatbot** - Access controlled through `site_id` → Site → `org_id`
- **ChatSession** - Access controlled through `chatbot_id` → Chatbot → Site → `org_id`

Note: `org_id` fields are UUIDs (not ForeignKeys) to avoid circular dependencies and maintain flexibility.

## Usage Examples

### Frontend Views

```python
# Automatic organization context via middleware
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_view(request):
    # org_id is automatically set by middleware
    org_id = getattr(request, 'org_id', None)

    # Get user's organizations
    user_orgs = get_user_organizations(request.user)
    org_ids = list(user_orgs.values_list('id', flat=True))

    # Filter resources by organizations
    sites = Site.objects.filter(org_id__in=org_ids)

    return Response({'sites': sites})
```

### Using Permission Decorators

```python
@api_view(['GET'])
@permission_classes([IsAuthenticated])
@require_site_access('site_id')
def get_site(request, site_id):
    # site_id is validated and user access is confirmed
    site = Site.objects.get(id=site_id)
    return Response({'site': site})
```

### Using Permission Utilities

```python
from apps.core.organization_permissions import check_site_access

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_site(request, site_id):
    try:
        # Validate access and get site
        site = check_site_access(request.user, site_id)

        # Update site...
        return Response({'message': 'Updated'})

    except ResourceNotInOrganizationError:
        return Response(
            {'error': 'You do not have access to this site'},
            status=403
        )
```

## Security Considerations

1. **Defense in Depth** - Multiple layers of protection:
   - Middleware validation
   - View-level filtering
   - Permission classes/decorators
   - Helper function validation

2. **Explicit Filtering** - All queries explicitly filter by organization IDs
3. **Access Validation** - All resource access goes through permission checks
4. **Logging** - Failed access attempts are logged for security monitoring
5. **Legacy Data** - Sites without `org_id` are allowed (with warnings) for backward compatibility

## Testing Organization Access

### Test with Different Organizations

1. Create multiple organizations
2. Create users with memberships to different organizations
3. Create resources (sites, chatbots) under different organizations
4. Verify users can only see/modify resources from their organizations

### Test Scenarios

- ✅ User can list only sites from their organizations
- ✅ User cannot access sites from other organizations
- ✅ User can create sites in their organization
- ✅ User cannot modify sites from other organizations
- ✅ User can perform bulk actions only on their organization's resources
- ✅ User without any organization sees empty data (not errors)
- ✅ Middleware sets org_id from user's primary organization
- ✅ Middleware validates org_id from URL parameter matches user's access

## Frontend Integration

The frontend should:

1. **Handle Organization Context** - Store the current organization context in application state
2. **Display Organization Switcher** - If user belongs to multiple organizations (future feature)
3. **Filter by Organization** - All API calls automatically use the organization context set by middleware
4. **Handle 403 Errors** - Show appropriate messages when organization access is denied

## Migration Path

For existing installations without organization support:

1. All existing sites have `org_id=None` initially (legacy data)
2. Create a default organization for existing users
3. Run a migration to assign `org_id` to all existing sites based on their owner
4. Update `org_id` for all indexing jobs based on their site's organization

## Future Enhancements

1. **Organization Switcher** - Allow users to switch between organizations they belong to
2. **Primary Organization Flag** - Mark one organization as primary per user
3. **Role-Based Permissions** - Different permission levels within organizations (admin, member, viewer)
4. **Cross-Organization Sharing** - Allow specific resources to be shared across organizations
5. **Organization Quotas** - Enforce different limits per organization based on their plan
