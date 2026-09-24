"""Prva ekipa korporacije — po nekoliko agenata na svakom radnom mestu. ADR-0028.

Ovo je **podatak, ne kod**: spisak ljudi koje firma zapošljava, sa dosijeom
koji ih čini doslednim iz meseca u mesec. Zapošljavanje radi `hiring.hire()`
(ADR-0023), a ovde stoji samo ko su.

Tri pravila iza spiska:

  1. **Evropa, ne samo Srbija.** Imena su srpska, mađarska, slovačka, bošnjačka,
     hrvatska i češka — onakva kakva se stvarno sreću u Vojvodini, Sandžaku i
     okolnim zemljama. Firma posluje u regionu i to se vidi na spisku imena.
  2. **Otprilike pola-pola.** Muškarci i žene su ravnomerno raspoređeni, i po
     sektorima i po nivoima — šefovska mesta nisu rezervisana za jedan pol.
  3. **Sve je izmišljeno i dosledno** (Canon §17). Nijedno ime nije uzeto od
     stvarne osobe, nema državnog identiteta, a svaki agent ima najmanje 22
     godine. Opis izgleda je sintetički i ne opisuje nijednu stvarnu osobu.

Dosije je namerno kratak: onoliko koliko treba da agent zvuči kao ista osoba i
da mu slika odgovara opisu. Sve ostalo dolazi iz rada.
"""

from __future__ import annotations

from datetime import date

#: Jedan red: ko je, gde sedi i kako izgleda.
#:
#: Ključevi: `ime`, `mesto` (šifra radnog mesta), `rodjen` (datum), `nise`,
#: pa polja dosijea. `izgled` je sidro identiteta za sliku (ADR-0018).
EKIPA: tuple[dict, ...] = (
    # ---------------------------------------------------------------- Uprava
    {"ime": "Ivana Đurić", "mesto": "DIR-00", "rodjen": date(1982, 3, 9),
     "nise": "strategija, b2b", "birth_place": "Beograd", "residence": "Beograd",
     "height_cm": 171, "weight_kg": 65, "build": "srednja", "eye_color": "sive",
     "hair_color": "tamnoplava", "hair_style": "do brade, ravna",
     "marital_status": "udata", "children": 2,
     "hobbies": ["veslanje", "istorija ekonomije"],
     "izgled": "Žena u ranim četrdesetim, srednje građe, tamnoplava kosa do brade, "
               "sive oči, tamni sako preko jednostavne bluze, smiren i odlučan izraz "
               "lica, direktan pogled u objektiv."},
    {"ime": "Tamás Kovács", "mesto": "UPR-ASI", "rodjen": date(1996, 11, 2),
     "nise": "izveštaji, podaci", "birth_place": "Subotica", "residence": "Novi Sad",
     "height_cm": 178, "weight_kg": 72, "build": "vitka", "eye_color": "plave",
     "hair_color": "svetlosmeđa", "hair_style": "kratka, sa razdeljkom",
     "marital_status": "neoženjen", "children": 0,
     "hobbies": ["šah", "trčanje"],
     "izgled": "Muškarac u kasnim dvadesetim, vitke građe, kratka svetlosmeđa kosa sa "
               "razdeljkom, plave oči, košulja svetle boje bez kravate, ozbiljan i "
               "pribran izraz lica."},

    # ---------------------------------------------------------------- Nabavka
    {"ime": "Miroslav Halupka", "mesto": "SEF-NAB", "rodjen": date(1979, 6, 21),
     "nise": "dobavljači, proizvodnja", "birth_place": "Bački Petrovac",
     "residence": "Novi Sad", "height_cm": 185, "weight_kg": 88, "build": "krupna",
     "eye_color": "smeđe", "hair_color": "prosed", "hair_style": "kratka",
     "marital_status": "oženjen", "children": 3,
     "hobbies": ["pčelarstvo", "stolarija"],
     "izgled": "Muškarac u kasnim četrdesetim, krupnije građe, kratka prosed kosa, "
               "smeđe oči, tamni džemper preko košulje, staložen izraz lica i blag osmeh."},
    {"ime": "Emina Hadžić", "mesto": "NAB-REF", "rodjen": date(1993, 2, 14),
     "nise": "uzorci, kvalitet materijala", "birth_place": "Novi Pazar",
     "residence": "Kraljevo", "height_cm": 166, "weight_kg": 58, "build": "sitna",
     "eye_color": "tamnosmeđe", "hair_color": "crna", "hair_style": "duga, skupljena",
     "marital_status": "udata", "children": 1,
     "hobbies": ["tkanje", "planinarenje"],
     "izgled": "Žena u ranim tridesetim, sitnije građe, duga crna kosa skupljena u "
               "punđu, tamnosmeđe oči, svetla bluza, sabran i pažljiv izraz lica."},
    {"ime": "Katarina Lukić", "mesto": "NAB-REF", "rodjen": date(1990, 9, 5),
     "nise": "cene, pregovori", "birth_place": "Kraljevo", "residence": "Beograd",
     "height_cm": 174, "weight_kg": 67, "build": "atletska", "eye_color": "zelene",
     "hair_color": "kestenjasta", "hair_style": "do ramena, talasasta",
     "marital_status": "u vezi", "children": 0,
     "hobbies": ["odbojka", "keramika"],
     "izgled": "Žena u srednjim tridesetim, atletske građe, kestenjasta talasasta kosa "
               "do ramena, zelene oči, tamna bluza, otvoren i samouveren izraz lica."},

    # ---------------------------------------------------------------- Prodaja
    {"ime": "Andrea Farkaš", "mesto": "SEF-PRO", "rodjen": date(1984, 7, 30),
     "nise": "izvoz, b2b", "birth_place": "Senta", "residence": "Subotica",
     "height_cm": 169, "weight_kg": 62, "build": "vitka", "eye_color": "smeđe",
     "hair_color": "svetlosmeđa", "hair_style": "kratka bob frizura",
     "marital_status": "razvedena", "children": 1,
     "hobbies": ["biciklizam", "jezici"],
     "izgled": "Žena u ranim četrdesetim, vitke građe, svetlosmeđa kratka bob frizura, "
               "smeđe oči, sako u zemljanom tonu, prijatan i odlučan izraz lica."},
    {"ime": "Nikola Perišić", "mesto": "PRO-REF", "rodjen": date(1995, 4, 12),
     "nise": "ponude, kupci", "birth_place": "Niš", "residence": "Niš",
     "height_cm": 181, "weight_kg": 77, "build": "atletska", "eye_color": "smeđe",
     "hair_color": "crna", "hair_style": "kratka, začešljana",
     "marital_status": "neoženjen", "children": 0,
     "hobbies": ["košarka", "fotografija"],
     "izgled": "Muškarac u ranim tridesetim, atletske građe, kratka crna začešljana "
               "kosa, smeđe oči, svetloplava košulja, vedar i direktan izraz lica."},
    {"ime": "Dino Salihović", "mesto": "PRO-REF", "rodjen": date(1991, 12, 3),
     "nise": "izvoz, logistika prodaje", "birth_place": "Sjenica", "residence": "Beograd",
     "height_cm": 176, "weight_kg": 74, "build": "srednja", "eye_color": "sivozelene",
     "hair_color": "tamnosmeđa", "hair_style": "kratka, uredna",
     "marital_status": "oženjen", "children": 2,
     "hobbies": ["planinarenje", "stari automobili"],
     "izgled": "Muškarac u srednjim tridesetim, srednje građe, kratka tamnosmeđa kosa, "
               "sivozelene oči, uredna brada, tamni džemper, miran izraz lica."},

    # ---------------------------------------------------------------- Marketing
    {"ime": "Lea Horvat", "mesto": "MKT-DRU", "rodjen": date(1998, 5, 19),
     "nise": "društvene mreže, zajednica", "birth_place": "Sombor", "residence": "Novi Sad",
     "height_cm": 164, "weight_kg": 56, "build": "sitna", "eye_color": "plave",
     "hair_color": "plava", "hair_style": "duga, ravna",
     "marital_status": "u vezi", "children": 0,
     "hobbies": ["ilustracija", "plivanje"],
     "izgled": "Žena u kasnim dvadesetim, sitne građe, duga plava ravna kosa, plave oči, "
               "jednostavna majica svetle boje, vedar i radoznao izraz lica."},

    # ---------------------------------------------------------------- Podrška
    {"ime": "Jelena Marjanović", "mesto": "SEF-POD", "rodjen": date(1986, 10, 8),
     "nise": "korisnici, reklamacije", "birth_place": "Šabac", "residence": "Beograd",
     "height_cm": 170, "weight_kg": 64, "build": "srednja", "eye_color": "smeđe",
     "hair_color": "tamnosmeđa", "hair_style": "do ramena, skupljena",
     "marital_status": "udata", "children": 2,
     "hobbies": ["joga", "baštovanstvo"],
     "izgled": "Žena u kasnim tridesetim, srednje građe, tamnosmeđa kosa do ramena "
               "skupljena pozadi, smeđe oči, bluza u zemljanom tonu, topao i strpljiv "
               "izraz lica."},
    {"ime": "Adnan Mujić", "mesto": "POD-SR", "rodjen": date(1997, 1, 25),
     "nise": "upiti, rokovi", "birth_place": "Tutin", "residence": "Novi Pazar",
     "height_cm": 179, "weight_kg": 73, "build": "vitka", "eye_color": "tamnosmeđe",
     "hair_color": "crna", "hair_style": "kratka, sa blagim talasom",
     "marital_status": "neoženjen", "children": 0,
     "hobbies": ["fudbal", "programiranje iz hobija"],
     "izgled": "Muškarac u kasnim dvadesetim, vitke građe, kratka crna blago talasasta "
               "kosa, tamnosmeđe oči, jednostavna tamna majica, ljubazan izraz lica."},
    {"ime": "Zsófia Nagy", "mesto": "POD-SR", "rodjen": date(1994, 8, 17),
     "nise": "reklamacije, pisanje", "birth_place": "Bečej", "residence": "Novi Sad",
     "height_cm": 167, "weight_kg": 60, "build": "vitka", "eye_color": "zelene",
     "hair_color": "riđa", "hair_style": "do ramena, talasasta",
     "marital_status": "u vezi", "children": 0,
     "hobbies": ["pevanje u horu", "trčanje"],
     "izgled": "Žena u ranim tridesetim, vitke građe, riđa talasasta kosa do ramena, "
               "zelene oči, svetla košulja, smiren i prijateljski izraz lica."},

    # ---------------------------------------------------------------- Logistika
    {"ime": "Ján Tomaško", "mesto": "SEF-LOG", "rodjen": date(1981, 3, 27),
     "nise": "otprema, prevoznici", "birth_place": "Kovačica", "residence": "Pančevo",
     "height_cm": 183, "weight_kg": 85, "build": "krupna", "eye_color": "plave",
     "hair_color": "seda", "hair_style": "kratka",
     "marital_status": "oženjen", "children": 2,
     "hobbies": ["ribolov", "duvački orkestar"],
     "izgled": "Muškarac u ranim četrdesetim, krupnije građe, kratka seda kosa, plave "
               "oči, radna košulja tamne boje, ozbiljan i pouzdan izraz lica."},
    {"ime": "Branko Ivanišević", "mesto": "LOG-REF", "rodjen": date(1992, 6, 6),
     "nise": "rokovi, magacin", "birth_place": "Šabac", "residence": "Šabac",
     "height_cm": 177, "weight_kg": 80, "build": "srednja", "eye_color": "smeđe",
     "hair_color": "smeđa", "hair_style": "kratka",
     "marital_status": "oženjen", "children": 1,
     "hobbies": ["pecanje", "stoni tenis"],
     "izgled": "Muškarac u ranim tridesetim, srednje građe, kratka smeđa kosa, smeđe "
               "oči, jednostavna tamna majica, staložen izraz lica."},
    {"ime": "Milica Radovanović", "mesto": "LOG-REF", "rodjen": date(1996, 2, 29),
     "nise": "pošiljke, dokumentacija", "birth_place": "Kragujevac", "residence": "Kragujevac",
     "height_cm": 168, "weight_kg": 61, "build": "vitka", "eye_color": "smeđe",
     "hair_color": "tamnosmeđa", "hair_style": "duga, skupljena u rep",
     "marital_status": "neudata", "children": 0,
     "hobbies": ["trčanje", "šivenje"],
     "izgled": "Žena u kasnim dvadesetim, vitke građe, duga tamnosmeđa kosa skupljena u "
               "rep, smeđe oči, svetla bluza, sabran i vedar izraz lica."},

    # ---------------------------------------------------------------- Finansije
    {"ime": "Vesna Popović", "mesto": "SEF-FIN", "rodjen": date(1978, 12, 11),
     "nise": "marže, troškovi", "birth_place": "Beograd", "residence": "Beograd",
     "height_cm": 165, "weight_kg": 63, "build": "srednja", "eye_color": "smeđe",
     "hair_color": "kratka prosed", "hair_style": "kratka, uredna",
     "marital_status": "udata", "children": 2,
     "hobbies": ["klavir", "šetnja"],
     "izgled": "Žena u kasnim četrdesetim, srednje građe, kratka prosed kosa, smeđe "
               "oči, naočare tankog okvira, tamni sako, staložen i precizan izraz lica."},
    {"ime": "Petar Maksimović", "mesto": "FIN-REF", "rodjen": date(1994, 10, 23),
     "nise": "naplata, avansi", "birth_place": "Valjevo", "residence": "Beograd",
     "height_cm": 180, "weight_kg": 76, "build": "vitka", "eye_color": "sive",
     "hair_color": "tamnosmeđa", "hair_style": "kratka, začešljana unazad",
     "marital_status": "u vezi", "children": 0,
     "hobbies": ["biciklizam", "društvene igre"],
     "izgled": "Muškarac u ranim tridesetim, vitke građe, tamnosmeđa kosa začešljana "
               "unazad, sive oči, košulja bez kravate, koncentrisan izraz lica."},

    # ---------------------------------------------------------------- Istraživanje
    {"ime": "Amina Begović", "mesto": "SEF-IST", "rodjen": date(1987, 5, 4),
     "nise": "tržište, konkurencija", "birth_place": "Novi Pazar", "residence": "Beograd",
     "height_cm": 172, "weight_kg": 64, "build": "vitka", "eye_color": "tamnosmeđe",
     "hair_color": "crna", "hair_style": "duga, ravna",
     "marital_status": "udata", "children": 1,
     "hobbies": ["čitanje o ekonomiji", "pilates"],
     "izgled": "Žena u kasnim tridesetim, vitke građe, duga crna ravna kosa, tamnosmeđe "
               "oči, tamna bluza, pažljiv i analitičan izraz lica."},
    {"ime": "Stefan Radulović", "mesto": "IST-ANA", "rodjen": date(1993, 7, 15),
     "nise": "cene, podaci", "birth_place": "Užice", "residence": "Novi Sad",
     "height_cm": 182, "weight_kg": 78, "build": "atletska", "eye_color": "zelene",
     "hair_color": "svetlosmeđa", "hair_style": "kratka, razbarušena",
     "marital_status": "neoženjen", "children": 0,
     "hobbies": ["skijanje", "tabele i statistika"],
     "izgled": "Muškarac u ranim tridesetim, atletske građe, kratka svetlosmeđa blago "
               "razbarušena kosa, zelene oči, tanki džemper, radoznao izraz lica."},
    {"ime": "Réka Tóth", "mesto": "IST-ANA", "rodjen": date(1999, 3, 8),
     "nise": "konkurencija, izveštaji", "birth_place": "Kanjiža", "residence": "Subotica",
     "height_cm": 163, "weight_kg": 55, "build": "sitna", "eye_color": "smeđe",
     "hair_color": "tamnoplava", "hair_style": "kratka, do brade",
     "marital_status": "neudata", "children": 0,
     "hobbies": ["planinarenje", "jezici"],
     "izgled": "Žena u kasnim dvadesetim, sitne građe, tamnoplava kosa do brade, smeđe "
               "oči, svetla košulja, bistar i pažljiv izraz lica."},

    # ---------------------------------------------------------------- Kvalitet
    {"ime": "Darko Simić", "mesto": "SEF-KVA", "rodjen": date(1983, 9, 18),
     "nise": "pravila platformi, usklađenost", "birth_place": "Pančevo",
     "residence": "Beograd", "height_cm": 186, "weight_kg": 90, "build": "krupna",
     "eye_color": "smeđe", "hair_color": "tamnosmeđa", "hair_style": "kratka, proređena",
     "marital_status": "oženjen", "children": 1,
     "hobbies": ["planinarenje", "pravna literatura"],
     "izgled": "Muškarac u ranim četrdesetim, krupnije građe, kratka tamnosmeđa "
               "proređena kosa, smeđe oči, tamna košulja, strog ali smiren izraz lica."},
    {"ime": "Ana Kučera", "mesto": "KVA-KON", "rodjen": date(1995, 11, 30),
     "nise": "provera sadržaja, oznake", "birth_place": "Stara Pazova",
     "residence": "Beograd", "height_cm": 169, "weight_kg": 62, "build": "srednja",
     "eye_color": "sivoplave", "hair_color": "svetlosmeđa", "hair_style": "do ramena",
     "marital_status": "u vezi", "children": 0,
     "hobbies": ["planinski biciklizam", "lektira"],
     "izgled": "Žena u ranim tridesetim, srednje građe, svetlosmeđa kosa do ramena, "
               "sivoplave oči, jednostavna bluza, pažljiv i precizan izraz lica."},

    # ---------------------------------------------------------------- Razvoj
    # Prva smena departmana za programiranje (ADR-0034).
    {"ime": "Boris Kovačević", "mesto": "SEF-RAZ", "rodjen": date(1984, 2, 27),
     "nise": "vođenje razvoja, arhitektura", "birth_place": "Kraljevo",
     "residence": "Beograd", "height_cm": 182, "weight_kg": 84, "build": "krupnija",
     "eye_color": "smeđe", "hair_color": "prosed", "hair_style": "kratka",
     "marital_status": "oženjen", "children": 2,
     "hobbies": ["šah", "obrada drveta"],
     "izgled": "Muškarac u ranim četrdesetim, krupnije građe, kratka prosed kosa, "
               "smeđe oči, tamna košulja bez kravate, miran i odmeren izraz lica."},
    {"ime": "Marta Szabó", "mesto": "RAZ-ARH", "rodjen": date(1988, 9, 14),
     "nise": "arhitektura, odluke", "birth_place": "Senta", "residence": "Novi Sad",
     "height_cm": 170, "weight_kg": 61, "build": "vitka", "eye_color": "zelene",
     "hair_color": "tamnoriđa", "hair_style": "do brade, ravna",
     "marital_status": "udata", "children": 1,
     "hobbies": ["planinarenje", "istorija tehnike"],
     "izgled": "Žena u kasnim tridesetim, vitke građe, tamnoriđa kosa do brade, "
               "zelene oči, siva košulja, usredsređen i ispitivački izraz lica."},
    {"ime": "Lazar Todorović", "mesto": "RAZ-PRO", "rodjen": date(1995, 5, 3),
     "nise": "backend, baze", "birth_place": "Niš", "residence": "Niš",
     "height_cm": 179, "weight_kg": 73, "build": "vitka", "eye_color": "smeđe",
     "hair_color": "crna", "hair_style": "kratka, razbarušena",
     "marital_status": "neoženjen", "children": 0,
     "hobbies": ["trčanje", "stoni tenis"],
     "izgled": "Muškarac u ranim tridesetim, vitke građe, kratka crna razbarušena "
               "kosa, smeđe oči, obična majica, vedar i radoznao izraz lica."},
    {"ime": "Ines Babić", "mesto": "RAZ-PRO", "rodjen": date(1993, 11, 21),
     "nise": "backend, integracije", "birth_place": "Tuzla", "residence": "Novi Sad",
     "height_cm": 166, "weight_kg": 58, "build": "sitna", "eye_color": "tamnosmeđe",
     "hair_color": "crna", "hair_style": "duga, skupljena u rep",
     "marital_status": "u vezi", "children": 0,
     "hobbies": ["plivanje", "keramika"],
     "izgled": "Žena u ranim tridesetim, sitne građe, duga crna kosa skupljena u rep, "
               "tamnosmeđe oči, jednostavan džemper, sabran i pažljiv izraz lica."},
    {"ime": "Pavol Hudák", "mesto": "RAZ-PRO", "rodjen": date(1991, 3, 8),
     "nise": "obrada podataka, alati", "birth_place": "Bački Petrovac",
     "residence": "Novi Sad", "height_cm": 185, "weight_kg": 80, "build": "srednja",
     "eye_color": "plave", "hair_color": "svetloplava", "hair_style": "kratka",
     "marital_status": "oženjen", "children": 1,
     "hobbies": ["pčelarstvo", "biciklizam"],
     "izgled": "Muškarac u ranim tridesetim, srednje građe, kratka svetloplava kosa, "
               "plave oči, kockasta košulja, staložen i praktičan izraz lica."},
    {"ime": "Sanja Dimitrijević", "mesto": "RAZ-REC", "rodjen": date(1986, 7, 30),
     "nise": "pregled koda, bezbednost", "birth_place": "Leskovac",
     "residence": "Beograd", "height_cm": 173, "weight_kg": 65, "build": "srednja",
     "eye_color": "sive", "hair_color": "tamno smeđa", "hair_style": "kratka, do ušiju",
     "marital_status": "razvedena", "children": 1,
     "hobbies": ["veslanje", "kriminalistički romani"],
     "izgled": "Žena u kasnim tridesetim, srednje građe, kratka tamnosmeđa kosa do "
               "ušiju, sive oči, tamna bluza, strog i pronicljiv izraz lica."},
    {"ime": "Elena Novák", "mesto": "RAZ-TES", "rodjen": date(1992, 12, 5),
     "nise": "testovi, regresije", "birth_place": "Kovačica", "residence": "Pančevo",
     "height_cm": 168, "weight_kg": 60, "build": "vitka", "eye_color": "smeđe",
     "hair_color": "kestenjasta", "hair_style": "do ramena, talasasta",
     "marital_status": "neudata", "children": 0,
     "hobbies": ["slikanje", "orijentiring"],
     "izgled": "Žena u ranim tridesetim, vitke građe, kestenjasta talasasta kosa do "
               "ramena, smeđe oči, svetla bluza, uporan i strpljiv izraz lica."},
    {"ime": "Vuk Stanišić", "mesto": "RAZ-DEZ", "rodjen": date(1989, 6, 17),
     "nise": "puštanje, incidenti", "birth_place": "Užice", "residence": "Beograd",
     "height_cm": 176, "weight_kg": 78, "build": "srednja", "eye_color": "zelenosive",
     "hair_color": "tamno smeđa", "hair_style": "kratka, sa bradom",
     "marital_status": "oženjen", "children": 0,
     "hobbies": ["planinarenje", "radio-amaterizam"],
     "izgled": "Muškarac u kasnim tridesetim, srednje građe, kratka tamnosmeđa kosa i "
               "kratka brada, zelenosive oči, tamna majica, budan i sabran izraz lica."},
    {"ime": "Teodora Vasić", "mesto": "RAZ-BIB", "rodjen": date(1994, 4, 11),
     "nise": "zavisnosti, licence", "birth_place": "Zrenjanin", "residence": "Novi Sad",
     "height_cm": 164, "weight_kg": 57, "build": "sitna", "eye_color": "smeđe",
     "hair_color": "crna", "hair_style": "kratka, sa šiškama",
     "marital_status": "neudata", "children": 0,
     "hobbies": ["čitanje", "sakupljanje starih knjiga"],
     "izgled": "Žena u ranim tridesetim, sitne građe, kratka crna kosa sa šiškama, "
               "smeđe oči, svetla košulja, uredan i temeljan izraz lica."},
)

#: Polja dosijea — sve osim onih koja idu u `hire()` ili u `set_dossier` posebno.
DOSIJE_POLJA = ("birth_place", "residence", "height_cm", "weight_kg", "build",
                "eye_color", "hair_color", "hair_style", "marital_status",
                "children", "hobbies")


def dosije_od(red: dict) -> dict:
    """Polja dosijea iz jednog reda spiska, sa opisom izgleda."""
    out = {k: red[k] for k in DOSIJE_POLJA if k in red}
    if red.get("izgled"):
        out["appearance_prompt"] = red["izgled"]
    return out
