-- =============================================================================
-- Seed lookup values for the Always & Furever donor database.
-- Safe to run once after schema.sql. Edit/extend as the rescue's needs grow.
-- =============================================================================

-- Sources -------------------------------------------------------------------
INSERT INTO sources (code, label, category) VALUES
  ('stripe',          'Stripe',                 'gateway'),
  ('paypal',          'PayPal',                 'gateway'),
  ('zeffy',           'Zeffy',                  'gateway'),
  ('givewp',          'GiveWP / WordPress',     'gateway'),
  ('facebook',        'Facebook',               'gateway'),
  ('check',           'Check',                  'offline'),
  ('cash',            'Cash',                   'offline'),
  ('in_kind',         'In-Kind Gift',           'in_kind'),
  ('wishlist_amazon', 'Amazon Wishlist',        'wishlist'),
  ('wishlist_chewy',  'Chewy Wishlist',         'wishlist'),
  ('wishlist_walmart','Walmart Wishlist',       'wishlist'),
  ('corporate',       'Corporate Sponsorship',  'other'),
  ('event',           'Event Donation',         'other'),
  ('auction',         'Auction Purchase',       'other'),
  ('matching_gift',   'Matching Gift',          'other'),
  ('other',           'Other',                  'other');

-- Payment methods -----------------------------------------------------------
INSERT INTO payment_methods (code, label) VALUES
  ('card',    'Credit/Debit Card'),
  ('ach',     'Bank Transfer / ACH'),
  ('paypal',  'PayPal Balance'),
  ('check',   'Check'),
  ('cash',    'Cash'),
  ('in_kind', 'In-Kind (non-cash)'),
  ('other',   'Other');

-- Funds / designations ------------------------------------------------------
INSERT INTO funds (code, label) VALUES
  ('general',  'General Fund'),
  ('medical',  'Medical Fund'),
  ('foster',   'Foster Program'),
  ('spay_neuter', 'Spay/Neuter'),
  ('facility', 'Facility / Operations'),
  ('unrestricted', 'Unrestricted');

-- Tribute types -------------------------------------------------------------
INSERT INTO tribute_types (code, label) VALUES
  ('in_memory',        'In Memory Of'),
  ('in_honor',         'In Honor Of'),
  ('pet_memorial',     'Pet Memorial'),
  ('special_occasion', 'Special Occasion');

-- A default system user so imports/notes have an author before real accounts.
INSERT INTO users (username, display_name, role) VALUES
  ('system', 'System / Import', 'admin');
