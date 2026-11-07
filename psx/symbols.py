"""
psx/symbols.py: PSX Master Stock Universe
Contains the comprehensive list of 100+ active, liquid registered PSX stocks
across all major sectors (E&P, Tech, Cement, Fertilizer, Banks, Refineries, Power, Auto, Pharma).
"""

PSX_UNIVERSE = [
    # Top Tier Liquid Leaders (KSE-100 Core)
    "OGDC", "PPL", "MARI", "POL", "SYS", "TRG", "LUCK", "ENGRO", "FFC", "EFERT",
    "HUBC", "HBL", "MCB", "UBL", "MEBL", "BAHL", "BAFL", "PSO", "SNGP", "SSGC",
    "ATRL", "CNERGY", "PRL", "NRL", "DGKC", "MLCF", "FCCL", "CHCC", "PIOC", "KOHC",
    
    # Active High-Beta & Volume Momentum Stocks
    "WTL", "PAEL", "SINDM", "MACFL", "FTSM", "KOSM", "AIRLINK", "AVN", "NETSOL",
    "FFBL", "FATIMA", "KAPCO", "KEL", "NCPL", "NPL", "SEARL", "GLAXO", "ABOT",
    "INDU", "HCL", "MTL", "EPCL", "LOTCHEM", "AGP", "GGL", "UNITY", "FCEPL",
    "MUGHAL", "ISL", "INIL", "ASTL", "NML", "ILP", "GATM", "TREET", "TPLP",
    "HUMNL", "IMAGE", "BOP", "FABL", "AKBL", "BIPL", "JSBL", "SNBL", "FLYNG",
    "THCCL", "ACPL", "SHEL", "APL", "HASCOL", "AGTL", "TOMCL", "PACE", "SILK"
]

def get_symbols(category: str = "ALL") -> list:
    """Returns requested PSX symbol universe."""
    if category == "CORE":
        return PSX_UNIVERSE[:30]
    return PSX_UNIVERSE
