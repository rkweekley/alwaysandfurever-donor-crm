"""
Build the SQLite database from db/schema.sql + db/seed_lookups.sql and load a
small set of DEMO donors/donations so the app has something to show.

Safe to re-run: it rebuilds donor_crm.sqlite from scratch each time.
NO REAL DONOR DATA lives here — all names below are invented.
"""
import os, sqlite3, hashlib

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "donor_crm.sqlite")
SCHEMA = os.path.join(BASE, "db", "schema.sql")
SEED = os.path.join(BASE, "db", "seed_lookups.sql")


def c(dollars):  # dollars -> integer cents
    return int(round(dollars * 100))


def main():
    if os.path.exists(DB):
        os.remove(DB)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    with open(SCHEMA) as f:
        db.executescript(f.read())
    with open(SEED) as f:
        db.executescript(f.read())

    # staff user for note authorship
    db.execute("INSERT INTO users (username, display_name, email, role) VALUES (?,?,?,?)",
               ("ksmith", "Karen Smith", "karen@alwaysandfurever.org", "admin"))

    def sid(code):
        return db.execute("SELECT id FROM sources WHERE code=?", (code,)).fetchone()[0]

    def pmid(code):
        r = db.execute("SELECT id FROM payment_methods WHERE code=?", (code,)).fetchone()
        return r[0] if r else None

    def fid(code):
        r = db.execute("SELECT id FROM funds WHERE code=?", (code,)).fetchone()
        return r[0] if r else None

    def ttid(code):
        r = db.execute("SELECT id FROM tribute_types WHERE code=?", (code,)).fetchone()
        return r[0] if r else None

    # campaigns
    db.execute("""INSERT INTO campaigns (code,label,start_date,end_date,goal_cents)
                  VALUES ('spring26','Spring Appeal 2026','2026-03-01','2026-05-31',?)""", (c(10000),))
    db.execute("""INSERT INTO campaigns (code,label,start_date,end_date,goal_cents)
                  VALUES ('givingtue25','Giving Tuesday 2025','2025-12-02','2025-12-02',?)""", (c(15000),))
    spring = db.execute("SELECT id FROM campaigns WHERE code='spring26'").fetchone()[0]
    gtue = db.execute("SELECT id FROM campaigns WHERE code='givingtue25'").fetchone()[0]

    # ---- demo donors: (type, first, last, org, household, email, phone, addr, city, st, zip, recurring) ----
    donors = [
        ("individual","Margaret","Holloway",None,None,"margaret.holloway@example.com","740-555-0118","118 River Rd","Beverly","OH","45715",1),
        ("individual","David","Chen",None,None,"dchen@example.com","614-555-0143","22 Oakdale Ave","Columbus","OH","43201",0),
        ("individual","Sofia","Ramirez",None,None,"sofia.r@example.com","740-555-0177",None,None,None,None,1),
        ("organization",None,None,"Marietta Veterinary Group",None,"giving@mvg.example","740-555-0200","9 Greene St","Marietta","OH","45750",0),
        ("household",None,None,None,"The Patterson Family","patterson.home@example.com","330-555-0162","450 Maple Dr","Akron","OH","44303",0),
        ("individual","James","O'Brien",None,None,"jobrien@example.com",None,"77 Hillcrest Ln","Parkersburg","WV","26101",0),
        ("individual","Aisha","Williams",None,None,"aisha.w@example.com","304-555-0199","12 Sunset Blvd","Vienna","WV","26105",1),
        ("organization",None,None,"Buckeye Pet Supply Co.",None,"donations@buckeyepet.example","614-555-0233","1500 Industrial Pkwy","Columbus","OH","43215",0),
        ("individual","Robert","Klein",None,None,"rklein@example.com","740-555-0150","8 Pine St","Zanesville","OH","43701",0),
        ("individual","Emily","Foster",None,None,"efoster@example.com","740-555-0166",None,"Belpre","OH","45714",0),
    ]
    donor_ids = []
    for row in donors:
        cur = db.execute("""INSERT INTO donors
            (donor_type,first_name,last_name,organization_name,household_name,
             primary_email,primary_phone,address_line1,city,state,postal_code,
             preferred_contact,is_recurring_donor)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (row[0],row[1],row[2],row[3],row[4],row[5],row[6],row[7],row[8],row[9],row[10],
             "email", row[11]))
        did = cur.lastrowid
        donor_ids.append(did)
        if row[5]:
            db.execute("INSERT INTO donor_emails (donor_id,email,is_primary) VALUES (?,?,1)",(did,row[5]))
        if row[6]:
            db.execute("INSERT INTO donor_phones (donor_id,phone,is_primary) VALUES (?,?,1)",(did,row[6]))

    # secondary email on Margaret (dedup demo)
    db.execute("INSERT INTO donor_emails (donor_id,email,is_primary) VALUES (?,?,0)",(donor_ids[0],"mholloway.work@example.com"))

    # tags
    for name in ("Major Prospect","Volunteer","Monthly Donor","Event Attendee","Corporate"):
        db.execute("INSERT INTO tags (name) VALUES (?)",(name,))
    def tag(did, name):
        tid = db.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()[0]
        db.execute("INSERT OR IGNORE INTO donor_tags (donor_id,tag_id) VALUES (?,?)",(did,tid))
    tag(donor_ids[0],"Major Prospect"); tag(donor_ids[0],"Monthly Donor")
    tag(donor_ids[3],"Corporate"); tag(donor_ids[7],"Corporate")
    tag(donor_ids[6],"Monthly Donor"); tag(donor_ids[4],"Event Attendee")

    # batch
    h = hashlib.sha256(b"demo").hexdigest()
    db.execute("""INSERT INTO import_batches (source_id,filename,file_hash,uploaded_by,status,
                  row_count,imported_count,skipped_count,committed_at)
                  VALUES (?,?,?,1,'committed',24,24,0,datetime('now'))""",
               (sid("stripe"),"stripe_2026_q1.csv",h))
    batch = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    # ---- donations: (donor_idx, date, amount, fee, source, pay, fund, campaign, recurring, in_kind, tribute, honoree, receipt) ----
    D = [
        (0,"2026-01-05",25,0.95,"stripe","card","general",None,1,0,None,None,"sent"),
        (0,"2026-02-05",25,0.95,"stripe","card","general",None,1,0,None,None,"sent"),
        (0,"2026-03-05",25,0.95,"stripe","card","general",None,1,0,None,None,"unsent"),
        (1,"2025-12-02",500,14.80,"paypal","paypal","medical",None,0,0,None,None,"sent"),
        (1,"2026-03-15",250,7.55,"stripe","card","medical",None,0,0,None,None,"unsent"),
        (2,"2026-01-20",15,0.74,"zeffy","card","general",None,1,0,None,None,"sent"),
        (2,"2026-02-20",15,0.74,"zeffy","card","general",None,1,0,None,None,"sent"),
        (2,"2026-03-20",15,0.74,"zeffy","card","general",None,1,0,None,None,"unsent"),
        (3,"2026-02-10",2500,0,"corporate","check","medical",None,0,0,None,None,"sent"),
        (4,"2026-03-08",100,0,"check","check","general",None,0,0,"in_memory","Max (their dog)","unsent"),
        (5,"2025-12-02",75,2.48,"facebook","card","general",None,0,0,None,None,"not_required"),
        (6,"2026-01-12",20,0.88,"stripe","card","general",None,1,0,None,None,"sent"),
        (6,"2026-02-12",20,0.88,"stripe","card","general",None,1,0,None,None,"sent"),
        (6,"2026-03-12",20,0.88,"stripe","card","general",None,1,0,None,None,"unsent"),
        (7,"2026-02-28",1000,0,"corporate","check","facility",None,0,0,None,None,"sent"),
        (8,"2026-03-18",50,0,"cash","cash","general",None,0,0,None,None,"not_required"),
        (9,"2026-03-22",0,0,"wishlist_chewy","in_kind","medical",None,0,1,None,None,"not_required"),
        (1,"2026-03-25",150,4.65,"stripe","card","general",None,0,0,"in_honor","Dr. Patel","unsent"),
        (4,"2025-12-02",250,0,"check","check","general",None,0,0,None,None,"sent"),
    ]
    for r in D:
        didx,date,amt,fee,src,pay,fund,camp,rec,ink,trib,hon,receipt = r
        amount = c(amt); feec = c(fee); net = amount - feec
        camp_id = gtue if date.startswith("2025-12") else (spring if date >= "2026-03-01" else None)
        db.execute("""INSERT INTO donations
            (donor_id,donation_date,amount_cents,fee_cents,net_cents,source_id,payment_method_id,
             fund_id,campaign_id,is_recurring,is_in_kind,in_kind_description,
             tribute_type_id,tribute_honoree,receipt_status,import_batch_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (donor_ids[didx],date,amount,feec,net,sid(src),pmid(pay),fid(fund),camp_id,
             rec,ink,("Case of dog food, est. value $60" if ink else None),
             ttid(trib) if trib else None, hon, receipt, batch))

    # notes
    notes = [
        (0,"call","Called to thank for monthly gift. Interested in sponsoring the medical fund.",1,"2026-04-15"),
        (0,"prospect","Major donor prospect — mentioned a possible year-end gift.",0,None),
        (1,"email","Asked for an annual giving summary for taxes.",1,"2026-04-10"),
        (3,"meeting","Vet group wants to formalize quarterly sponsorship.",0,None),
        (4,"general","Gift made in memory of their dog Max. Send a tribute card.",1,"2026-04-05"),
        (6,"preference","Prefers email only — no phone calls please.",0,None),
    ]
    for didx,ntype,text,fu,fudate in notes:
        db.execute("""INSERT INTO donor_notes (donor_id,note_type,note_text,follow_up_needed,follow_up_date,author_id)
                      VALUES (?,?,?,?,?,1)""",(donor_ids[didx],ntype,text,fu,fudate))

    # duplicate candidate (Emily Foster vs a near-dupe would go here; flag one open for demo)
    db.execute("""INSERT INTO duplicate_candidates (donor_a_id,donor_b_id,match_reason,confidence,status)
                  VALUES (?,?,?,?,'open')""",(donor_ids[1],donor_ids[8],"fuzzy_name",0.62))

    # recompute rolling giving columns from the view
    db.execute("""UPDATE donors SET
        donation_total_cents = COALESCE((SELECT donation_total_cents FROM vw_donor_giving v WHERE v.donor_id=donors.id),0),
        gift_count           = COALESCE((SELECT gift_count           FROM vw_donor_giving v WHERE v.donor_id=donors.id),0),
        first_gift_date      = (SELECT first_gift_date FROM vw_donor_giving v WHERE v.donor_id=donors.id),
        last_gift_date       = (SELECT last_gift_date  FROM vw_donor_giving v WHERE v.donor_id=donors.id),
        largest_gift_cents   = COALESCE((SELECT largest_gift_cents FROM vw_donor_giving v WHERE v.donor_id=donors.id),0)
    """)

    db.commit()
    n_d = db.execute("SELECT COUNT(*) FROM donors").fetchone()[0]
    n_g = db.execute("SELECT COUNT(*) FROM donations").fetchone()[0]
    tot = db.execute("SELECT COALESCE(SUM(amount_cents),0) FROM donations").fetchone()[0]
    db.close()
    print(f"Seeded {n_d} donors, {n_g} donations, total ${tot/100:,.2f} -> {DB}")


if __name__ == "__main__":
    main()
