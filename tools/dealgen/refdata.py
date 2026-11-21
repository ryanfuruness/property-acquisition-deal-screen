"""Static reference data for the synthetic deal generator: names, brokerages, location copy.

Everything here is fictional. Landmarks and roads are real places in Dubai (used only as
location context); every building, plot, brokerage, person and company is invented.
"""

FOOTER = "Synthetic document for demonstration. Fictional property."

# ---------------------------------------------------------------------------
# Tenant names. Grouped so first and last names pair plausibly.
# ---------------------------------------------------------------------------
NAME_GROUPS = {
    "indian": (
        ["Rahul", "Priya", "Arjun", "Sneha", "Vikram", "Anjali", "Rohan", "Kavya", "Suresh", "Deepa",
         "Nikhil", "Meera", "Arun", "Lakshmi", "Sanjay", "Pooja", "Kiran", "Ravi", "Divya", "Manoj",
         "Abhishek", "Shalini", "Vivek", "Neha", "Ajith", "Bindu"],
        ["Menon", "Sharma", "Nair", "Iyer", "Kapoor", "Reddy", "Pillai", "Desai", "Joshi", "Kulkarni",
         "Bhat", "Rao", "Verma", "Shetty", "Krishnan", "Mathew", "Varghese", "Gupta", "Malhotra",
         "Chandran", "Thomas", "Kurian", "Agarwal", "Banerjee"]),
    "pakistani": (
        ["Imran", "Ayesha", "Bilal", "Sana", "Usman", "Hina", "Faisal", "Zainab", "Hamza", "Mariam",
         "Kashif", "Nadia", "Asad", "Rabia", "Waqas", "Saima"],
        ["Qureshi", "Siddiqui", "Malik", "Chaudhry", "Butt", "Sheikh", "Abbasi", "Raza", "Mirza",
         "Hashmi", "Khalid", "Anwar", "Iqbal", "Javed"]),
    "filipino": (
        ["Maria", "Jose", "Angelica", "Mark", "Kristine", "John Paul", "Rowena", "Jerome", "Lovely",
         "Ramon", "Cherry", "Arnel", "Jocelyn", "Rodel"],
        ["Santos", "Reyes", "Cruz", "Bautista", "Ocampo", "Garcia", "Mendoza", "Villanueva",
         "Dela Cruz", "Aquino", "Ramos", "Navarro", "Manalo", "Pascual"]),
    "levantine": (
        ["Omar", "Layla", "Khaled", "Rania", "Tarek", "Dina", "Yousef", "Hala", "Samer", "Nour", "Rami",
         "Lina", "Fadi", "Maya", "Hassan", "Reem", "Ziad", "Joelle"],
        ["Haddad", "Khoury", "Nasser", "Saleh", "Mansour", "Aziz", "Hamdan", "Barakat", "Sabbagh",
         "Darwish", "Najjar", "Kanaan", "Shami", "Awad", "Tannous", "Hijazi"]),
    "egyptian": (
        ["Ahmed", "Mona", "Mahmoud", "Yasmin", "Mostafa", "Heba", "Karim", "Noha", "Sherif", "Dalia",
         "Amr", "Rasha"],
        ["Abdelrahman", "El-Sayed", "Fahmy", "Ibrahim", "Shalaby", "Gamal", "Zaki", "Fouad", "Hegazy",
         "Soliman", "Ragab", "Lotfy"]),
    "european": (
        ["James", "Sophie", "Thomas", "Emma", "Daniel", "Charlotte", "Lukas", "Anna", "Marco", "Giulia",
         "Pierre", "Claire", "Oliver", "Hannah", "Stefan", "Elena", "Niall", "Freya"],
        ["Whitfield", "Hartley", "Becker", "Moreau", "Rossi", "Kowalski", "Lindqvist", "Fischer",
         "Brennan", "Dubois", "Novak", "Russo", "Ashworth", "Keller", "Marchetti", "Holm", "Doyle",
         "Vermeulen"]),
    "russian": (
        ["Dmitry", "Anastasia", "Sergey", "Ekaterina", "Alexei", "Olga", "Ivan", "Natalia", "Pavel",
         "Yulia", "Maxim", "Daria"],
        ["Volkov", "Morozov", "Sokolov", "Petrov", "Orlov", "Kuznetsov", "Lebedev", "Pavlov",
         "Smirnov", "Belov", "Egorov", "Zaitsev"]),
    "chinese": (
        ["Wei", "Li Na", "Jun", "Mei", "Hao", "Xiu Ying", "Chen", "Ying", "Lei", "Fang", "Bo", "Lan"],
        ["Zhang", "Wang", "Liu", "Chen", "Yang", "Huang", "Zhao", "Wu", "Zhou", "Xu", "Lin", "He"]),
    "african": (
        ["Chinedu", "Amina", "Kwame", "Grace", "Tendai", "Fatou", "Samuel", "Esther", "Joseph",
         "Blessing", "Emeka", "Wanjiru"],
        ["Okafor", "Mensah", "Mwangi", "Diallo", "Banda", "Adeyemi", "Otieno", "Kamau", "Asante",
         "Ndlovu", "Eze", "Owusu"]),
    "srilankan": (
        ["Nuwan", "Dilani", "Kasun", "Chamari", "Ruwan", "Ishara"],
        ["Perera", "Fernando", "Silva", "Jayasinghe", "Wickramasinghe", "Bandara"]),
}
FEMALE_FIRST = {
    "Priya", "Sneha", "Anjali", "Kavya", "Deepa", "Meera", "Lakshmi", "Pooja", "Divya", "Shalini",
    "Neha", "Bindu", "Ayesha", "Sana", "Hina", "Zainab", "Mariam", "Nadia", "Rabia", "Saima", "Maria",
    "Angelica", "Kristine", "Rowena", "Lovely", "Cherry", "Jocelyn", "Layla", "Rania", "Dina", "Hala",
    "Nour", "Lina", "Maya", "Reem", "Joelle", "Mona", "Yasmin", "Heba", "Noha", "Dalia", "Rasha",
    "Sophie", "Emma", "Charlotte", "Anna", "Giulia", "Claire", "Hannah", "Elena", "Freya", "Anastasia",
    "Ekaterina", "Olga", "Natalia", "Yulia", "Daria", "Li Na", "Mei", "Xiu Ying", "Ying", "Fang", "Lan",
    "Amina", "Grace", "Fatou", "Esther", "Blessing", "Wanjiru", "Dilani", "Chamari", "Ishara",
}

AREA_NATIONALITY_WEIGHTS = {
    "JVC": {"indian": 22, "pakistani": 8, "filipino": 8, "levantine": 12, "egyptian": 8, "european": 14,
            "russian": 12, "african": 6, "chinese": 3, "srilankan": 3},
    "Dubai Silicon Oasis": {"indian": 28, "pakistani": 14, "filipino": 12, "levantine": 10, "egyptian": 12,
                            "european": 5, "russian": 3, "african": 6, "chinese": 4, "srilankan": 6},
    "International City": {"indian": 18, "pakistani": 16, "filipino": 14, "levantine": 4, "egyptian": 8,
                           "european": 1, "russian": 2, "african": 12, "chinese": 18, "srilankan": 7},
    "Business Bay": {"indian": 20, "pakistani": 6, "filipino": 5, "levantine": 14, "egyptian": 8,
                     "european": 22, "russian": 15, "african": 4, "chinese": 4, "srilankan": 2},
    "Al Barsha": {"indian": 22, "pakistani": 8, "filipino": 8, "levantine": 18, "egyptian": 14,
                  "european": 14, "russian": 8, "african": 4, "chinese": 2, "srilankan": 2},
}

COMPANY_PREFIX = [
    "Bluewave", "Northstar", "Crescent Line", "Silverleaf", "Al Fajr Al Jadeed", "Greenfield Arc", "Summit Peak",
    "Redwood Gulf", "Desert Lantern", "Pearl Coast", "Zenith Arc", "Horizon Point", "Sapphire Line", "Ironbridge",
    "Gulfway", "Seabreeze", "Palmyra Star", "Cobalt Ridge", "Starline", "Amberley", "Al Muntaha Al Thahabi",
    "Bright Arc", "Unity Link", "Coral Gate", "Saqr Al Sahraa", "Tidewater", "Meadowlark", "Quartzline",
    "Al Reem Al Fiddi", "Kingfisher Bay", "Lumen Grid", "Copperleaf", "Westgate Arc", "Orion Path",
]
COMPANY_ACTIVITY = [
    "Technical Services", "General Trading", "Electromechanical Works", "Facilities Management", "Logistics",
    "Building Contracting", "IT Solutions", "Marine Services", "Catering Services", "Medical Centre",
    "Engineering Consultants", "Cargo Services", "Security Services", "Auto Spare Parts Trading",
    "Software Development", "Interior Decoration", "Travel & Tourism", "Hospitality Management",
]
COMPANY_SUFFIX_BY_AREA = {
    "Dubai Silicon Oasis": ["FZCO", "FZ-LLC", "L.L.C", "LLC"],
    "International City": ["L.L.C", "LLC", "Co. L.L.C"],
}
COMPANY_SUFFIX_DEFAULT = ["LLC", "L.L.C", "L.L.C.", "LLC"]

RETAIL_TENANTS = [
    "Daily Fresh Mini Mart L.L.C", "Cedar Leaf Pharmacy L.L.C", "Lotus Bloom Laundry Services",
    "Urban Brew Cafe L.L.C", "Quick Fix Mobile Phones Repairing", "Al Saha Al Khadra Grocery",
    "Bright Smile Dental Clinic L.L.C", "Pure Cuts Gents Salon", "Spice Route Restaurant L.L.C",
    "Corner Basket Supermarket L.L.C", "Glow Ladies Beauty Salon", "Swift Wash Car Care",
]

# ---------------------------------------------------------------------------
# Brokerages (fictional). Each has a visual theme and its own vocabulary.
# ---------------------------------------------------------------------------
BROKERS = {
    "harbour_crest": {
        "name": "Harbour & Crest Real Estate Advisory",
        "short": "Harbour & Crest",
        "division": "Capital Markets | Residential Investment",
        "orn": "ORN 41827",
        "address": "Level 14, Capital Gate Offices, Business Bay, Dubai, UAE",
        "phone": "+971 4 000 7700",
        "web": "www.harbourcrest.example",
        "contacts": [
            ("Karim Haddad MRICS", "Director, Capital Markets", "BRN 58213", "+971 50 000 2290",
             "k.haddad@harbourcrest.example"),
            ("Sophie Whitlock", "Associate Director, Investment", "BRN 61904", "+971 55 000 0815",
             "s.whitlock@harbourcrest.example"),
        ],
        "confidential": "Strictly private and confidential. Prepared for the named recipient only and not for onward distribution.",
    },
    "marwah_stone": {
        "name": "Marwah & Stone Capital",
        "short": "Marwah & Stone",
        "division": "Investment Sales",
        "orn": "ORN 37590",
        "address": "Suite 705, Al Wasl Court, Sheikh Zayed Road, Dubai, UAE",
        "phone": "+971 4 000 4120",
        "web": "www.marwahstone.example",
        "contacts": [
            ("Faisal Marwah", "Managing Partner", "BRN 44120", "+971 50 000 3018", "faisal@marwahstone.example"),
            ("Elena Novak", "Senior Analyst", "BRN 66318", "+971 52 000 1147", "elena.novak@marwahstone.example"),
        ],
        "confidential": "Confidential Information Memorandum. Subject to the signed confidentiality undertaking.",
    },
    "dunecrest": {
        "name": "Dunecrest Real Estate Brokers L.L.C",
        "short": "DUNECREST",
        "division": "Commercial & Investment Division",
        "orn": "ORN 29364",
        "address": "Office 2306, Fortune Arc Tower, JLT Cluster T, Dubai, UAE",
        "phone": "+971 4 000 2211",
        "web": "www.dunecrest.example",
        "contacts": [
            ("Rizwan Akhtar", "Head of Investment Sales", "BRN 52277", "+971 56 000 9182",
             "rizwan@dunecrest.example"),
        ],
        "confidential": "Private & Confidential - exclusive mandate. Do not share without written consent of Dunecrest.",
    },
    "meridian_gate": {
        "name": "Meridian Gate Properties",
        "short": "Meridian Gate",
        "division": "Whole Building Investments",
        "orn": "ORN 33058",
        "address": "Office 1102, Burjuman Business Tower Annex, Bur Dubai, Dubai, UAE",
        "phone": "+971 4 000 8060",
        "web": "www.meridiangate.example",
        "contacts": [
            ("Tarek Nasser", "Senior Investment Consultant", "BRN 49731", "+971 50 000 6604",
             "tarek.n@meridiangate.example"),
            ("Anjali Pillai", "Investment Consultant", "BRN 63302", "+971 58 000 4790",
             "anjali.p@meridiangate.example"),
        ],
        "confidential": "Confidential - for discussion purposes only.",
    },
    "saffron_key": {
        "name": "Saffron Key Realty",
        "short": "Saffron Key Realty",
        "division": "Buildings & Investment",
        "orn": "ORN 45512",
        "address": "Shop 6, Al Nahda Plaza, Al Qusais, Dubai, UAE",
        "phone": "+971 4 000 5522",
        "web": "www.saffronkey.example",
        "contacts": [
            ("Imran Siddiqui", "Sales Manager - Buildings", "BRN 47885", "+971 55 000 2471",
             "imran@saffronkey.example"),
        ],
        "confidential": "Confidential. Information provided by the owner; buyer to verify.",
    },
}

# ---------------------------------------------------------------------------
# Location copy by area (real roads and landmarks; property fictional).
# ---------------------------------------------------------------------------
LOCATION = {
    "JVC": {
        "dld_area": "Al Barsha South Fourth",
        "intro": ("Jumeirah Village Circle (JVC) is a master-planned freehold community of low- and mid-rise "
                  "residential buildings and townhouses between Al Khail Road (E44) and Sheikh Mohammed Bin "
                  "Zayed Road (E311). It is one of Dubai's most actively rented mid-market locations, with a "
                  "deep tenant pool of young professionals and families working in Dubai Marina, JLT, "
                  "Al Barsha and Dubai Production City."),
        "access": [("Al Khail Road (E44)", "3 min"), ("Sheikh Mohammed Bin Zayed Road (E311)", "5 min"),
                   ("Circle Mall", "4 min"), ("Mall of the Emirates", "15 min"), ("Dubai Marina / JLT", "15 min"),
                   ("Downtown Dubai", "22 min"), ("Al Maktoum International Airport (DWC)", "30 min")],
    },
    "Dubai Silicon Oasis": {
        "dld_area": "Nadd Hessa",
        "intro": ("Dubai Silicon Oasis (DSO) is an integrated technology park and freehold residential community "
                  "at the junction of the Dubai-Al Ain Road (E66) and Sheikh Mohammed Bin Zayed Road (E311). "
                  "Residents are drawn from the park's technology and education employers, Dubai Academic "
                  "City and the wider Al Warqa and Mirdif catchment, supporting steady occupancy."),
        "access": [("Dubai-Al Ain Road (E66)", "2 min"), ("Sheikh Mohammed Bin Zayed Road (E311)", "4 min"),
                   ("Silicon Central Mall", "5 min"), ("Dubai Academic City", "8 min"),
                   ("Dubai International Airport (DXB)", "18 min"), ("Downtown Dubai", "20 min")],
    },
    "International City": {
        "dld_area": "International City",
        "intro": ("International City is a large freehold residential and commercial community off Al Awir Road "
                  "(E44) and Sheikh Mohammed Bin Zayed Road (E311), next to Dragon Mart. It offers some of "
                  "Dubai's most affordable rents and attracts a large, price-sensitive tenant base, including "
                  "corporate staff accommodation. Rents have been more resilient than prime areas in 2026."),
        "access": [("Al Awir Road (E44)", "3 min"), ("Sheikh Mohammed Bin Zayed Road (E311)", "4 min"),
                   ("Dragon Mart", "5 min"), ("Dubai Silicon Oasis", "8 min"),
                   ("Dubai International Airport (DXB)", "15 min"), ("Downtown Dubai", "22 min")],
    },
    "Business Bay": {
        "dld_area": "Business Bay",
        "intro": ("Business Bay is a central freehold mixed-use district along the Dubai Water Canal, directly "
                  "south of Downtown Dubai, with frontage to Sheikh Zayed Road and Al Khail Road. It combines "
                  "offices, hotels and high-rise residential towers and draws professional tenants working in "
                  "Downtown, DIFC and the Business Bay office market."),
        "access": [("Business Bay Metro Station", "6 min walk"), ("Al Khail Road (E44)", "3 min"),
                   ("Sheikh Zayed Road (E11)", "4 min"), ("Dubai Mall / Downtown Dubai", "5 min"),
                   ("DIFC", "8 min"), ("Dubai International Airport (DXB)", "15 min")],
    },
    "Al Barsha": {
        "dld_area": "Al Barsha",
        "intro": ("Al Barsha is an established central district between Sheikh Zayed Road and Al Khail Road, "
                  "anchored by Mall of the Emirates and the Red Line metro. Its residential stock ranges from "
                  "mid-rise buildings in Al Barsha 1 to the high-rise towers of Barsha Heights (TECOM), which "
                  "serve employees of Dubai Internet City, Dubai Media City and Al Barsha's hotels."),
        "access": [("Sheikh Zayed Road (E11)", "3 min"), ("Mall of the Emirates", "6 min"),
                   ("Dubai Internet City Metro Station", "7 min"), ("Al Khail Road (E44)", "6 min"),
                   ("Dubai Marina", "12 min"), ("Downtown Dubai", "18 min")],
    },
}

UNIT_LABELS = {"studio": "Studio", "1br": "1 Bedroom", "2br": "2 Bedroom", "3br": "3 Bedroom", "retail": "Retail"}
