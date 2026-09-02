"""Load a snapshot of finance emails (pulled from Gmail) into the warehouse's
`emails` table so Ganak can query email data. One-time snapshot; safe to re-run
(upsert by message_id). Bank-advice amounts live inside PDF attachments (NULL here).
Run via connect_gmail.bat.
"""
import os
import psycopg2

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = os.path.join(HERE, "..", ".env")


def get_db_url():
    for line in open(ENV, encoding="utf-8"):
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DATABASE_URL not found in backend/.env")


# (message_id, date, direction, category, counterparty, sender, subject, amount)
RECORDS = [
    ("1a01a0b79331a8bb","2026-08-19","incoming","bank_payment_advice","KSB","dbauto.email41@deutsche.bank.in","Payment advice E3S2608191894231",None),
    ("19febacb9aa5b816","2026-08-10","incoming","bank_payment_advice","KSB","dbae.india6@deutsche.bank.in","Payment advice E3S2608105148320",None),
    ("19fcb09fda531021","2026-08-04","incoming","bank_payment_advice","KSB","dbauto.email26@deutsche.bank.in","Payment advice E3S2608043940933",None),
    ("19f8352deefec7b5","2026-07-21","incoming","bank_payment_advice","KSB","dbae.india20@deutsche.bank.in","Payment advice E3S2607217910540",None),
    ("19f4bed68de7fc8b","2026-07-10","incoming","bank_payment_advice","KSB","dbauto.email30@deutsche.bank.in","Payment advice E3S2607101701325",None),
    ("19f22995e80d2480","2026-07-02","incoming","bank_payment_advice","KSB","dbauto.email32@deutsche.bank.in","Payment advice E3S2607027185468",None),
    ("19ebc1d7b5bd1a2e","2026-06-12","incoming","bank_payment_advice","KSB","dbae.india10@deutsche.bank.in","Payment advice E3S2606122002738",None),
    ("19e882592b70af90","2026-06-02","incoming","bank_payment_advice","KSB","dbauto.email39@deutsche.bank.in","Payment advice E3S2606023089551",None),
    ("19e69b29855fdaaf","2026-05-27","incoming","bank_payment_advice","KSB","dbae.india8@deutsche.bank.in","Payment advice E3S2605272540669",None),
    ("19e2cfbdc0c00374","2026-05-15","incoming","bank_payment_advice","KSB","dbauto.email39@deutsche.bank.in","Payment advice E3S2605151578331",None),
    ("19e0878dba500c18","2026-05-08","incoming","bank_payment_advice","KSB","dbauto.email32@deutsche.bank.in","Payment advice E3S2605089541201",None),
    ("19dac1c90392184d","2026-04-20","incoming","bank_payment_advice","KSB","dbauto.email30@deutsche.bank.in","Payment advice E3S2604207578539",None),
    ("19d7810a1947fc57","2026-04-10","incoming","bank_payment_advice","KSB","dbauto.email8@db.com","Payment advice E3S2604103204442",None),
    ("19d518848d5dc796","2026-04-03","incoming","bank_payment_advice","KSB","dbauto.email24@db.com","Payment advice E3S2604031332034",None),
    ("19d41b5bdd14ec9e","2026-03-31","incoming","bank_payment_advice","KSB","dbauto.email33@db.com","Payment advice E3S2603305423244",None),
    ("19cf69503d83d0cc","2026-03-16","incoming","bank_payment_advice","KSB","dbauto.email17@db.com","Payment advice E3S2603169746400",None),
    ("19cb20cf2e6602e5","2026-03-03","incoming","bank_payment_advice","KSB","dbauto.email30@db.com","Payment advice E3S2603037698974",None),
    ("19c8c41062dca27d","2026-02-23","incoming","bank_payment_advice","KSB","dbauto.email14@db.com","Payment advice E3S2602242015123",None),
    ("19c4d1635923c199","2026-02-11","incoming","bank_payment_advice","KSB","dbauto.email6@db.com","Payment advice E3S2602113444053",None),
    ("19fb25f254446f33","2026-07-30","incoming","payment_received","OJAS ENTERPRISES","message-service@sender.zoho-books.in","Payment Received from OJAS Enterprises",128301.00),
    ("19fb2645e69da8be","2026-07-30","incoming","payment_received","OJAS ENTERPRISES","message-service@sender.zoho-books.in","Payment Received from OJAS Enterprises",15399.00),
    ("19fb2bd4e09934e5","2026-07-30","incoming","payment_received","OJAS ENTERPRISES","message-service@sender.zoho-books.in","Payment Received from OJAS Enterprises",2557.60),
    ("19e90e263c54a816","2026-06-04","outgoing","vendor_bill","Ferrochem NDT Systems","info@ferrochem.net","Ferrochem - please make payment",4200.00),
    ("19eab30c60cbed84","2026-06-09","outgoing","vendor_bill","Ferrochem NDT Systems","info@ferrochem.net","Ferrochem - please make payment",9412.00),
    ("19f1c482b9a14014","2026-07-01","inbound","balance_confirmation","Shree Balaji Corporation","balajicorporation17@gmail.com","Balance confirmation",None),
    ("19e35aa028b28438","2026-05-17","inbound","balance_confirmation","Shree Balaji Corporation","accbalajicorporation2020@gmail.com","Balance confirmation as on 31.03.2026",63307.00),
    ("19f0dd4469d83dce","2026-06-28","outgoing","vendor_bill","Shree Balaji Corporation","balajicorporation17@gmail.com","Pending bills",None),
    ("19d5d35a72d12c23","2026-04-04","inbound","price_notice","Shree Balaji Corporation","balajicorporation17@gmail.com","Price revised - DP testing consumables",None),
    ("19ed72c4b10f4616","2026-06-17","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19d02c3599f5f303","2026-03-18","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19ce9021607c04ea","2026-03-13","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19cdeb5ecef58354","2026-03-11","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19cc4f680c9edd3a","2026-03-06","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19cbaa9aea588689","2026-03-04","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19ca0eafbfceb40c","2026-02-27","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19c969b57f7c7a3d","2026-02-25","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19c7cde26ebe8a93","2026-02-20","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19c7290756ad3b0a","2026-02-18","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19c58d20bda85c27","2026-02-13","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19c4e8493cac68e1","2026-02-11","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19c34c507c02f792","2026-02-06","inbound","purchase_order","KSB","rawsaheb.rautray@ksb.com","Pending Purchase Order Statement - KSB",None),
    ("19cf12126b5b0d07","2026-03-15","inbound","debit_note","KSB","akshaykumar.bhojakar@ksb.com","The Balaji Industries Debit",None),
    ("19f6face3d87fb86","2026-07-17","inbound","quotation","Devkate Enterprise","devkateenterprise@gmail.com","Labour Quotation",None),
]

_COLS = "message_id,email_date,direction,category,counterparty,sender,subject,amount"


def main():
    url = get_db_url()
    print(f"Connecting to warehouse... loading {len(RECORDS)} finance emails")
    conn = psycopg2.connect(url); conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            message_id TEXT PRIMARY KEY, email_date DATE, direction TEXT,
            category TEXT, counterparty TEXT, sender TEXT, subject TEXT, amount NUMERIC)""")
    for r in RECORDS:
        cur.execute(f"""INSERT INTO emails({_COLS}) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (message_id) DO UPDATE SET
              email_date=EXCLUDED.email_date, direction=EXCLUDED.direction,
              category=EXCLUDED.category, counterparty=EXCLUDED.counterparty,
              sender=EXCLUDED.sender, subject=EXCLUDED.subject, amount=EXCLUDED.amount""", r)
    cur.execute("SELECT COUNT(*) FROM emails")
    print(f"Done. 'emails' table now has {cur.fetchone()[0]} rows.")
    cur.execute("SELECT category, COUNT(*) FROM emails GROUP BY category ORDER BY 2 DESC")
    for cat, n in cur.fetchall():
        print(f"  {cat:22} {n}")
    conn.close()


if __name__ == "__main__":
    main()
