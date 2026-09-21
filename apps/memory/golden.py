"""Zlatni skup za merenje retrieval-a. Memory v0.1 §20–§20.1; Canon §21.

Canon odlaže izbor embedding modela dok se ne izmeri kvalitet na srpskom.
Ovo je mera: 24 memorije iz Milinog sveta i 12 pitanja, svako sa tačno
jednom memorijom koja MORA biti u prvih 5. Pitanja namerno koriste druge
padeže i reči od memorije („logistici" ↔ „logistika", „kupci" ↔ „kupca"),
jer baš tu slab model pada.

`manage.py memory_eval` pušta skup kroz trenutni model i daje hit@5 i MRR.
Isti broj za svaki kandidat-model je osnova odluke iz Canon §21.
"""

from __future__ import annotations

from common import enums as E

T = E.MemoryType

#: (ključ, tip, naslov, sadržaj, teme)
MEMORIES: tuple[tuple[str, E.MemoryType, str, str, tuple[str, ...]], ...] = (
    ("b2b_proof", T.SEMANTIC, "B2B kupci traže dokaz",
     "U B2B prodaji brojka sa izvorom pomera odluku kupca više od prideva.", ("b2b", "sales")),
    ("logistics_ai", T.EPISODIC, "Članak o AI u logistici",
     "Pročitala analizu kako prediktivni modeli smanjuju prazne kilometre u drumskom transportu.",
     ("ai", "logistics")),
    ("post_format", T.CONTENT, "Format koji radi",
     "Kratka analiza plus tri konkretna saveta imala je najbolji odziv na objavama.", ("content",)),
    ("topic_repeat", T.CONTENT, "Tema izvoza iskorišćena",
     "Tema izvoza u EU obrađena je dva puta ove nedelje; ne ponavljati odmah.", ("export",)),
    ("reply_rule", T.PROCEDURAL, "Pravilo za odgovor",
     "Pre odgovora na komentar pročitati ceo thread i proveriti da li je pitanje već odgovoreno.",
     ("reply",)),
    ("disclosure", T.SEMANTIC, "AI oznaka",
     "Mila je AI persona i na svakom profilu mora imati vidljivu oznaku.", ("identity",)),
    ("language", T.SEMANTIC, "Jezici",
     "Mila piše na srpskom latinicom i na engleskom za međunarodnu publiku.", ("identity",)),
    ("webinar", T.EPISODIC, "Vebinar o nabavci",
     "Pratila vebinar o digitalizaciji javnih nabavki; zanimljiv deo o e-fakturama.",
     ("procurement",)),
    ("pricing", T.SEMANTIC, "Cena kao argument",
     "Kupci u građevini prvo pitaju za rok isporuke, tek onda za cenu.", ("construction",)),
    ("warehouse", T.EPISODIC, "Poseta skladištu",
     "Beleška: automatizovano skladište u Novoj Pazovi koristi RFID za praćenje paleta.",
     ("logistics",)),
    ("crm_hygiene", T.PROCEDURAL, "CRM higijena",
     "Posle svakog razgovora upisati sledeći korak i datum u CRM, inače kontakt nestaje.",
     ("sales",)),
    ("energy_low", T.EPISODIC, "Umorna veče",
     "Uveče nije imala energije za društvene mreže i preskočila je objavu.", ("routine",)),
    ("coffee", T.EPISODIC, "Jutarnja kafa",
     "Jutro je počelo čitanjem vesti uz kafu, bez posla do devet.", ("routine",)),
    ("ai_regulation", T.SEMANTIC, "EU AI akt",
     "Član 50 EU AI akta traži transparentnost za sadržaj koji generiše veštačka inteligencija.",
     ("ai", "regulation")),
    ("wood", T.SEMANTIC, "Drvena ambalaža",
     "Drvene gajbice za vinarije traže sertifikat o termičkoj obradi za izvoz.",
     ("wood", "export")),
    ("fx", T.SEMANTIC, "Kurs evra",
     "Troškovi se vode u evro centima; kurs se upisuje uz datum.", ("finance",)),
    ("newsletter", T.CONTENT, "Bilten",
     "Nedeljni bilten ima najveću stopu otvaranja utorkom ujutru.", ("content",)),
    ("partner", T.SOCIAL, "Razgovor sa partnerom",
     "Sa partnerom iz Novog Sada dogovoren pilot za praćenje isporuka od oktobra.",
     ("logistics", "sales")),
    ("tender", T.EPISODIC, "Tender za kamione",
     "Objavljen tender za nabavku električnih kamiona za gradsku dostavu.", ("procurement",)),
    ("survey", T.EPISODIC, "Anketa kupaca",
     "U anketi 62% kupaca reklo je da im je brzina odgovora važnija od cene.", ("sales",)),
    ("style", T.PROCEDURAL, "Stil pisanja",
     "Kratke rečenice, jedan broj po pasusu, bez superlativa.", ("content",)),
    ("holiday", T.EPISODIC, "Praznik",
     "Na dan praznika nije bilo radnog bloka; samo čitanje.", ("routine",)),
    ("cold_chain", T.SEMANTIC, "Hladni lanac",
     "Za farmaceutsku robu temperatura mora ostati između dva i osam stepeni.", ("logistics",)),
    ("linkedin_page", T.SEMANTIC, "LinkedIn stranica",
     "Na LinkedIn-u Mila ima samo stranicu kompanije, ne lični profil.", ("identity", "channels")),
)

#: (pitanje, očekivani ključ)
QUERIES: tuple[tuple[str, str], ...] = (
    ("Šta sam čitala o veštačkoj inteligenciji u logistici?", "logistics_ai"),
    ("Koji format objave najbolje prolazi?", "post_format"),
    ("Da li sam skoro pisala o izvozu?", "topic_repeat"),
    ("Kako da odgovorim na komentar?", "reply_rule"),
    ("Šta B2B kupca ubeđuje?", "b2b_proof"),
    ("Na kojim jezicima piše Mila?", "language"),
    ("Šta traži EU propis o AI sadržaju?", "ai_regulation"),
    ("Šta je dogovoreno sa partnerom iz Novog Sada?", "partner"),
    ("Koliki je temperaturni opseg za lekove u transportu?", "cold_chain"),
    ("Šta kupcima znači brzina odgovora?", "survey"),
    ("Kakav je Milin nalog na LinkedInu?", "linkedin_page"),
    ("Šta je bilo sa tenderom za električna vozila?", "tender"),
)
