from .tenancy import clear_tenant_context


class TenantContextMiddleware:
    """Clears the Postgres tenant GUCs after every request so persistent
    connections can never carry one request's tenant context into the next."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            return self.get_response(request)
        finally:
            clear_tenant_context()
