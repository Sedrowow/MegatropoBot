from dataclasses import dataclass
from typing import List, Optional, Dict, Set
from enum import Enum, auto
from datetime import datetime

class FactionPermission(Enum:
    ADD_MEMBERS = auto()
    MANAGE_MONEY = auto()
    MANAGE_RANKS = auto()
    MANAGE_ALLIANCES = auto()
    MANAGE_ANNOUNCEMENTS = auto()

@dataclass
class Rank:
    name: str
    priority: int
    permissions: Set<FactionPermission]

@dataclass
class User:
    id: int
    balance: float = 2500
    faction_id: Optional[int] = None
    nation_id: Optional[int] = None
    rank_id: Optional[int] = None
    pending_invites: List[int] = None

@dataclass
class Faction:
    id: int
    name: str
    owner_id: int
    balance: float = 0
    nation_id: Optional[int] = None
    members: List[int] = None
    ranks: Dict[int, Rank] = None
    rank_assignments: Dict[int, int] = None  # user_id to rank_id mapping

@dataclass
class Nation:
    id: int
    name: str
    owner_id: int
    balance: float = 0
    factions: List[int] = None
    allies: List[int] = None

@dataclass
class PassIdentifier:
    colorless_part: str  # hex string for faction/nation combo
    colored_part: str    # hex string for user-specific colors
    faction_id: Optional[int] = None
    nation_id: Optional[int] = None

@dataclass
class UserPass:
    user_id: int
    faction_id: Optional[int]
    nation_id: Optional[int]
    issue_date: datetime
    expiry_date: datetime
    pass_identifier: PassIdentifier
    faction_rank: Optional[str] = None
    nation_rank: Optional[str] = None
