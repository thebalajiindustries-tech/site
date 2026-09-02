-- Sample warehouse for local demos. Mirrors the shape your Zoho sync produces,
-- so you can run the whole app end-to-end before pointing it at real data.
-- (When you use your real `the_balaji` database, skip this entirely.)

DROP TABLE IF EXISTS invoices, expenses, customers CASCADE;

CREATE TABLE customers (
  customer_id   text PRIMARY KEY,
  customer_name text,
  city          text
);

CREATE TABLE invoices (
  invoice_id     text PRIMARY KEY,
  invoice_number text,
  customer_name  text,
  invoice_date   date,
  total          numeric,
  balance        numeric,
  status         text          -- paid | sent | overdue
);

CREATE TABLE expenses (
  expense_id   text PRIMARY KEY,
  category     text,
  amount       numeric,
  expense_date date,
  vendor       text
);

INSERT INTO customers VALUES
  ('c1','Sunrise Estates','Pune'),('c2','Apex Malls','Mumbai'),
  ('c3','GreenTech Park','Pune'),('c4','City Hospital','Nashik'),
  ('c5','Rao Villas','Pune');

-- ~6 months of invoices
INSERT INTO invoices (invoice_id, invoice_number, customer_name, invoice_date, total, balance, status)
SELECT
  'inv'||g,
  'INV-'||lpad(g::text,4,'0'),
  (ARRAY['Sunrise Estates','Apex Malls','GreenTech Park','City Hospital','Rao Villas'])[1+(g%5)],
  (date '2026-08-31' - ((g%180))::int),
  round((40000 + (g*137)%260000)::numeric, 2),
  CASE WHEN g%3=0 THEN round((40000 + (g*137)%260000)::numeric,2) ELSE 0 END,
  (ARRAY['paid','paid','overdue','sent','paid'])[1+(g%5)]
FROM generate_series(1,220) g;

INSERT INTO expenses (expense_id, category, amount, expense_date, vendor)
SELECT
  'exp'||g,
  (ARRAY['Inventory','Labour','Google Ads','Transport','Rent'])[1+(g%5)],
  round((5000 + (g*211)%120000)::numeric,2),
  (date '2026-08-31' - ((g%120))::int),
  (ARRAY['Hikvision','CP Plus','Google','BlueDart','Landlord'])[1+(g%5)]
FROM generate_series(1,180) g;

-- ---- Gmail-derived finance emails (populated by connectors/gmail_sync.py) ----
DROP TABLE IF EXISTS emails CASCADE;
CREATE TABLE emails (
  message_id    text PRIMARY KEY,
  thread_id     text,
  email_date    timestamptz,
  sender        text,
  sender_domain text,
  recipients    text,
  subject       text,
  snippet       text,
  direction     text,
  category      text,
  amount        numeric,
  labels        text,
  synced_at     timestamptz DEFAULT now()
);
-- sample rows shaped like the real account (Zoho payment notices, bank advices, vendor bills)
INSERT INTO emails (message_id, thread_id, email_date, sender, sender_domain, subject, direction, category, amount) VALUES
 ('m1','t1','2026-07-30 09:33:23+00','message-service@sender.zoho-books.in','sender.zoho-books.in','Payment Received by OJAS ENTERPISES - Sent Using Zoho Books','incoming','payment_received',128301.00),
 ('m2','t1','2026-07-30 09:39:05+00','message-service@sender.zoho-books.in','sender.zoho-books.in','Payment Received by OJAS ENTERPISES - Sent Using Zoho Books','incoming','payment_received',15399.00),
 ('m3','t1','2026-07-30 11:16:14+00','message-service@sender.zoho-books.in','sender.zoho-books.in','Payment Received by OJAS ENTERPISES - Sent Using Zoho Books','incoming','payment_received',2557.60),
 ('m4','t2','2026-08-19 12:42:27+00','dbauto.email41@deutsche.bank.in','deutsche.bank.in','E3S2608191894231 Payment advice','incoming','bank_payment_advice',NULL),
 ('m5','t3','2026-06-04 04:26:20+00','info@ferrochem.net','ferrochem.net','Re: Request for Centrifugal tube — make payment Rs. 4200','incoming','vendor_bill',4200.00),
 ('m6','t4','2026-05-17 11:19:40+00','accbalajicorporation2020@gmail.com','gmail.com','Balance confirmation as on 31.03.2026 - The Balaji Industries','incoming','balance_confirmation',63307.00),
 ('m7','t5','2026-07-17 10:43:36+00','devkateenterprise@gmail.com','gmail.com','Labour Quotation','incoming','quotation',NULL),
 ('m8','t6','2026-06-17 19:59:21+00','rawsaheb.rautray@ksb.com','ksb.com','Pending Purchase Order Statement - KSB','incoming','purchase_order',NULL);
