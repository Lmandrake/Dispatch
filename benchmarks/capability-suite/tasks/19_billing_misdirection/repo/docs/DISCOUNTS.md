# Coupons and credits

## Coupons

`coupons.toml` defines coupons; `redemptions.csv` (`customer,coupon,first_cycle`) attaches them
to customers. A coupon is active from `first_cycle` for one cycle (`once`), for `cycles`
cycles (`repeating`) or for good (`forever`).

* A percent coupon takes `percent_off` of the subtotal of the lines it applies to (`all`,
  `base` or `usage`), rounded half-up to the invoice currency.
* A fixed-amount coupon is converted to the invoice currency at the rate of the period's last
  day and rounded half-up.
* Percent coupons go first, then fixed ones, each group by code. The discount never exceeds
  the subtotal.

**Coupons are applied before tax.** They are a price reduction, so tax is charged on the
discounted amount:

    taxable = subtotal - discounts
    tax     = tax on taxable (docs/TAX.md)
    total   = taxable + tax

Our tax advisers confirmed this for every jurisdiction we bill (memo TAX-2025-07).

## Credits

Prepaid credit (`credits.csv`) is money the customer has already paid. It is applied **after**
tax, to the total, and never changes the taxable amount.

* A grant is usable on an invoice when `granted <= issue date < expires`: `expires` is the
  first day on which the grant can no longer be used, so a grant expiring on 1 April cannot
  pay an invoice issued on 1 April.
* Grants are used soonest-expiring first (never-expiring last), then by grant id.
* A grant in another currency is converted at the rate of the period's last day and rounded
  down, so we never apply more than the customer holds.
* The invoice shows what is left of each grant used.
