# planted_violations

Synthetic repo with deliberate violations. Used by H2 regression tests
to validate that the universal detectors catch the expected anti-patterns.

Plant inventory (rule_id : count):

- `universal.circular_dependency`: 2 (billing↔users cycle, shipping↔reporting cycle)
- `universal.god_object`: 2 (OrderManager, UserAdmin)
- `universal.cyclomatic_complexity`: 6 (six high-CC functions across modules)

**Total: 10 expected findings**. Tests assert at least 8/10 are caught (plan H2 criterion).
