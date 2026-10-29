# Exchange rates

`fx_rates.csv` quotes each currency against USD (`per_usd`: units of the currency per 1 USD),
each quote applying from its `effective` day until the next quote for that currency. USD is
always 1.

Converting from currency A to currency B on day D uses the cross rate

    per_usd(B, D) / per_usd(A, D)

rounded half-even to 10 decimal places. Both quotes are the ones in effect **on D**, so the
cross rate changes whenever either currency gets a new quote. A to B to A need not round-trip
exactly; Finance accepted that.

Invoice amounts are converted from the plan currency at the rate of the last day of the
billing period, before rounding (docs/INVOICES.md). Credits and fixed coupons use the same
day. The reconciliation report converts invoice totals to USD at that day's rate too.

`fx.Converter` memoises cross rates because there are many lookups per run; one Converter is
shared by every invoice of a run. Memoising must never change a result: the same (A, B, D)
always gives the same rate, whatever was looked up before.
