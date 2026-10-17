"""Schema-completeness test (UX roadmap web-client follow-up, S0b).

Before this change, the operations below returned an untyped `{}` response
in the OpenAPI schema (their views build plain dicts by hand, with no
serializer DRF could introspect). `openapi-typescript` would then generate
`unknown` for them on the web client, defeating the whole point of
generating types from the schema. Each one now carries an `@extend_schema`
response annotation (see the `schema.py` modules next to each view). This
test asserts the schema actually reflects that — a response that drifts
back to untyped fails here before it fails silently on the web client.
"""
from django.test import TestCase
from drf_spectacular.generators import SchemaGenerator


class SchemaCompletenessTests(TestCase):
    # (method, [fragments the path must contain, in order], extra check)
    TARGETS = [
        ('get', ['analytics', 'summary']),
        ('get', ['analytics', 'trend']),
        ('get', ['properties', 'layout']),
        ('get', ['cash-movements']),
        ('get', ['payments', 'receipt']),
        ('get', ['expenses', 'summary']),
        ('get', ['expenses', 'attachment']),
        ('get', ['residents', '{']),  # the detail route, not the list
    ]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.schema = SchemaGenerator().get_schema(request=None, public=True)

    def _find_operation(self, method, fragments):
        for path, operations in self.schema['paths'].items():
            if not all(fragment in path for fragment in fragments):
                continue
            operation = operations.get(method)
            if operation is not None:
                return path, operation
        return None, None

    def _response_schema(self, operation):
        response = operation['responses']['200']
        if 'content' in response:
            return response['content']['application/json']['schema']
        return response  # drf-spectacular inlines a bare schema for some responses

    def test_every_listed_operation_has_a_typed_response(self):
        for method, fragments in self.TARGETS:
            with self.subTest(method=method, fragments=fragments):
                path, operation = self._find_operation(method, fragments)
                self.assertIsNotNone(path, f'no {method.upper()} operation matching {fragments}')
                schema = self._response_schema(operation)
                self.assertNotEqual(schema, {}, f'{method.upper()} {path} is still untyped ({{}})')
                is_typed = bool(schema.get('$ref')) or bool(schema.get('properties')) or bool(schema.get('allOf'))
                self.assertTrue(is_typed, f'{method.upper()} {path} response has no usable shape: {schema}')
