# Standard target fields

What every platform mapping points at. (⇒ table.column in db/schema.sql)

## Donor fields
- `first_name`         ⇒ donors.first_name
- `last_name`          ⇒ donors.last_name
- `organization_name`  ⇒ donors.organization_name
- `email`              ⇒ donors.primary_email / donor_emails.email
- `phone`              ⇒ donors.primary_phone / donor_phones.phone
- `address_line1`      ⇒ donors.address_line1
- `address_line2`      ⇒ donors.address_line2
- `city`               ⇒ donors.city
- `state`              ⇒ donors.state
- `postal_code`        ⇒ donors.postal_code
- `country`            ⇒ donors.country

## Donation fields
- `donation_date`      ⇒ donations.donation_date        (ISO YYYY-MM-DD)
- `amount`             ⇒ donations.amount_cents          (gross; parsed to cents)
- `fee`                ⇒ donations.fee_cents
- `net`                ⇒ donations.net_cents
- `currency`           ⇒ donations.currency
- `source`             ⇒ donations.source_id             (set by which template you use)
- `payment_method`     ⇒ donations.payment_method_id
- `campaign`           ⇒ donations.campaign_id
- `fund`               ⇒ donations.fund_id
- `is_recurring`       ⇒ donations.is_recurring          (0/1)
- `tribute_type`       ⇒ donations.tribute_type_id
- `tribute_honoree`    ⇒ donations.tribute_honoree
- `source_txn_id`      ⇒ donations.source_txn_id         (original platform id)
- `notes`              ⇒ donations.notes
