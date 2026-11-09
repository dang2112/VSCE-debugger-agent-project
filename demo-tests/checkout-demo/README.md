# Checkout demo

A standalone project for manually trying the debugger extension. It contains two
application modules and two test files. It is not imported by the frontend or
backend. The older ../main.py example is unchanged.

## Intended behavior

A customer's loyalty points determine the discount on the entire cart:

| Points | Discount |
| --- | --- |
| 0-499 | 0% |
| 500-999 | 10% |
| 1000 or more | 15% |

Item prices and loyalty points cannot be negative. Totals are rounded to cents.
A cart containing items priced 40 and 60 should therefore cost 85 at 1000 points.
The current implementation incorrectly charges 90 for that case.

## Files

- pricing.py: subtotal and checkout calculation.
- discounts.py: loyalty discount calculation.
- tests/test_checkout.py: exposes the checkout bug.
- tests/test_pricing.py: passes without exercising the faulty discount rule.

## Run the tests

From this directory, using Python with pytest installed:

```powershell
python -m pytest -q
```

Before repair, expect **1 failed, 1 passed**. After the correct repair, expect
**2 passed**. You can also use the backend virtual environment's Python executable.
The pytest.ini makes imports work when opening this as a standalone project.

## Try the full extension pipeline

1. Start the backend, then launch the frontend with F5.
2. In the Extension Development Host, open THIS checkout-demo folder as the project
   (not the frontend/backend parent folder), then open pricing.py.
3. Use agent mode and enable "Generate and verify a patch".
4. Set pythonDebugAgent.sourceRoot to "." and pythonDebugAgent.testTargets to
   ["tests"]. Keep automatic SBFL enabled. These are the extension defaults.
5. Send this request:

   > At exactly 1000 loyalty points, checkout_total([40, 60], 1000) returns 90,
   > but our documented loyalty rules say it should return 85. Investigate the
   > cause, propose a minimal fix, and verify it against the tests.

6. Optionally enter tests/test_checkout.py::test_checkout_at_1000_points in the
   failing pytest selectors field. Leave the suite setting as ["tests"] so SBFL
   also collects the passing test and verification runs the full suite.
7. Inspect the explanation, Open patch, and Session details. The baseline should
   reproduce the failure; a successful candidate should pass both tests.

The README also supplies intended behavior for the agent's document-search tools.
Document searches are model-selected, so they are not guaranteed on every run.
The backend proposes and verifies a patch in a copy; the demo remains broken until
YOU apply the reviewed patch. No reference solution file is included in the project.
