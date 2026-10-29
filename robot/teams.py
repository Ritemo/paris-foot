"""Correspondance des noms d'equipes : The Odds API -> football-data.co.uk."""
import difflib
import unicodedata

MANUEL = {
    # Ligue 1
    "AS Monaco": "Monaco", "Le Mans FC": "Le Mans", "Paris Saint Germain": "Paris SG", "RC Lens": "Lens",
    "Saint Etienne": "St Etienne", "Stade Rennais": "Rennes", "Olympique Lyonnais": "Lyon",
    # Premier League
    "Brighton and Hove Albion": "Brighton", "Coventry City": "Coventry", "Hull City": "Hull",
    "Ipswich Town": "Ipswich", "Leeds United": "Leeds", "Manchester City": "Man City",
    "Manchester United": "Man United", "Newcastle United": "Newcastle", "Nottingham Forest": "Nott'm Forest",
    "Tottenham Hotspur": "Tottenham", "Wolverhampton Wanderers": "Wolves", "West Ham United": "West Ham",
    "Leicester City": "Leicester", "Sheffield United": "Sheffield United", "Luton Town": "Luton",
    "Norwich City": "Norwich", "Stoke City": "Stoke", "Cardiff City": "Cardiff", "Swansea City": "Swansea",
    # Liga
    "Alavés": "Alaves", "Athletic Bilbao": "Ath Bilbao", "Atlético Madrid": "Ath Madrid", "CA Osasuna": "Osasuna",
    "Celta Vigo": "Celta", "Deportivo La Coruña": "La Coruna", "Elche CF": "Elche", "Espanyol": "Espanol",
    "Málaga": "Malaga", "Rayo Vallecano": "Vallecano", "Real Betis": "Betis",
    "Real Racing Club de Santander": "Santander", "Real Sociedad": "Sociedad", "Girona": "Girona",
    "Mallorca": "Mallorca", "Las Palmas": "Las Palmas", "Real Valladolid": "Valladolid", "Leganés": "Leganes",
    "Cádiz CF": "Cadiz", "Granada CF": "Granada", "Almería": "Almeria", "Real Oviedo": "Oviedo",
    "Sporting Gijón": "Sp Gijon",
    # Serie A
    "AC Milan": "Milan", "AS Roma": "Roma", "Atalanta BC": "Atalanta", "Inter Milan": "Inter",
    "Hellas Verona": "Verona", "Empoli": "Empoli", "Pisa": "Pisa", "Cremonese": "Cremonese",
    # Bundesliga
    "1. FC Köln": "FC Koln", "Bayer Leverkusen": "Leverkusen", "Borussia Dortmund": "Dortmund",
    "Borussia Monchengladbach": "M'gladbach", "Eintracht Frankfurt": "Ein Frankfurt", "FC Schalke 04": "Schalke 04",
    "FSV Mainz 05": "Mainz", "Hamburger SV": "Hamburg", "SC Freiburg": "Freiburg", "SC Paderborn": "Paderborn",
    "TSG Hoffenheim": "Hoffenheim", "VfB Stuttgart": "Stuttgart", "VfL Wolfsburg": "Wolfsburg",
    "FC St. Pauli": "St Pauli", "1. FC Heidenheim": "Heidenheim", "Holstein Kiel": "Holstein Kiel",
    "VfL Bochum": "Bochum", "Darmstadt 98": "Darmstadt", "1. FC Union Berlin": "Union Berlin",
}


def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    for w in ("fc ", " fc", "ac ", "as ", "cf ", " cf", "sc ", "1. ", "tsg ", "vfb ", "vfl ", "fsv ", "rc "):
        s = s.replace(w, " ")
    return " ".join(s.split())


def to_fd(name, fd_names):
    """Retourne le nom football-data correspondant, ou None."""
    if name in MANUEL and MANUEL[name] in fd_names:
        return MANUEL[name]
    if name in fd_names:
        return name
    normed = {_norm(n): n for n in fd_names}
    n = _norm(name)
    if n in normed:
        return normed[n]
    for k, v in normed.items():  # inclusion (ex. "monaco" dans "as monaco")
        if k and (k in n or n in k):
            return v
    m = difflib.get_close_matches(n, list(normed), n=1, cutoff=0.6)
    return normed[m[0]] if m else None
