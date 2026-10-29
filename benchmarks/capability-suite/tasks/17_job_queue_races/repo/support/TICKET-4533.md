# TICKET-4533: customer saw another customer's statement (sev 1, security)

Opened by: Trust & Safety

> Tenant `globex` downloaded a PDF statement that belonged to tenant `acme`.
> Both had requested the "monthly statement" export with the same report
> parameters within a few minutes of each other. The second request
> returned instantly with a result, without any job being run for
> `globex`. We use the result cache for the `render_statement` kind with a
> 10-minute TTL. Disabling the cache stops it.
