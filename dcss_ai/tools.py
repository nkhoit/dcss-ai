#!/usr/bin/env python3
"""DCSS game tools - provider-agnostic tool definitions."""

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Callable
from pydantic import BaseModel, Field

from dcss_ai.game import DCSSGame
from dcss_ai.providers.base import write_monologue


# --- Tool parameter models (internal validation) ---

class EmptyParams(BaseModel):
    pass

class DirectionParams(BaseModel):
    direction: str = Field(description="Direction: n/s/e/w/ne/nw/se/sw")

class SlotParams(BaseModel):
    key: str = Field(description="Inventory slot letter (a-z)")

class SlotDirectionParams(BaseModel):
    key: str = Field(description="Inventory slot letter (a-z)")
    direction: str = Field(description="Direction: n/s/e/w/ne/nw/se/sw")

class SlotOptionalDirectionParams(BaseModel):
    key: str = Field(description="Inventory slot letter (a-z)")
    direction: str = Field(default="", description="Direction: n/s/e/w/ne/nw/se/sw (optional)")

class OptionalSlotParams(BaseModel):
    key: str = Field(default="", description="Inventory slot letter (a-z), optional if only one worn")

class SpellParams(BaseModel):
    key: str = Field(description="Spell slot letter")
    direction: str = Field(default="", description="Direction to cast: n/s/e/w/ne/nw/se/sw (optional)")

class OverlayParams(BaseModel):
    thought: str = Field(default="", description="Brief one-liner about what you're thinking (shown to stream viewers)")

class DeathParams(BaseModel):
    cause: str = Field(default="", description="Brief cause of death")

class DeathJournalParams(BaseModel):
    cause: str = Field(description="Brief cause of death from game messages")
    reflection: str = Field(description="What could have helped — your reflection on this death")

class LearningParams(BaseModel):
    text: str = Field(description="A lesson learned from this game. Be specific and actionable. Include [situation: ...] tags when context-dependent. Example: '- Don't berserk when surrounded [situation: 3+ enemies, no corridor, post-berserk exhaustion = death]'")
    section: str = Field(default="Heuristics", description="Section: Hard Rules, Heuristics, Notes, Melee Builds, Caster Builds, Species Notes, or a new section name")

class StartGameParams(BaseModel):
    species_key: str = Field(default="b", description=(
        "Species key (0.34): a=Gnoll, b=Minotaur, c=Merfolk, d=Gargoyle, "
        "e=Mountain Dwarf, f=Draconian, g=Troll, h=Deep Elf, i=Armataur, "
        "j=Human, k=Kobold, l=Revenant, m=Demonspawn, n=Djinni, o=Spriggan, "
        "p=Tengu, q=Oni, r=Barachi, s=Coglin, t=Vine Stalker, u=Poltergeist, "
        "v=Demigod, w=Formicid, x=Naga, y=Octopode, z=Felid, A=Mummy"
    ))
    background_key: str = Field(default="f", description=(
        "Background key (0.34): a=Fighter, b=Gladiator, c=Monk, d=Hunter, "
        "e=Brigand, f=Berserker, g=Cinder Acolyte, h=Chaos Knight, "
        "i=Artificer, j=Shapeshifter, k=Wanderer, l=Delver, m=Warper, "
        "n=Hexslinger, o=Enchanter, p=Reaver, q=Hedge Wizard, r=Conjurer, "
        "s=Summoner, t=Necromancer, u=Forgewright, v=Fire Elementalist, "
        "w=Ice Elementalist, x=Air Elementalist, y=Earth Elementalist, z=Alchemist"
    ))
    weapon_key: str = Field(default="", description="Weapon key if prompted (a/b/etc, leave empty for auto)")

class MapParams(BaseModel):
    radius: int = Field(default=15, description="Map view radius (default 15)")

class MessagesParams(BaseModel):
    n: int = Field(default=10, description="Number of recent messages to return")


def _make_handler(dcss: DCSSGame, method_name: str, param_model: type, *args, **kwargs) -> Callable:
    """Create a handler function that validates params and calls a DCSS method."""
    def handler(params_dict: Dict[str, Any]) -> str:
        # Validate parameters using Pydantic model
        params = param_model(**params_dict)
        
        # Special case: write_learning doesn't use DCSSGame
        if hasattr(params, 'text') and method_name == 'write_learning':
            learnings_path = Path(__file__).parent.parent / "learnings.md"
            section = getattr(params, 'section', 'Heuristics')
            text = params.text
            
            content = learnings_path.read_text() if learnings_path.exists() else ""
            
            # Find the section header and append after its last bullet
            header = f"## {section}"
            if header in content:
                # Find the next section header after this one
                header_pos = content.index(header)
                after_header = content[header_pos + len(header):]
                next_section = after_header.find("\n## ")
                if next_section == -1:
                    # Last section — append at end
                    content = content.rstrip() + f"\n- {text}\n"
                else:
                    insert_pos = header_pos + len(header) + next_section
                    content = content[:insert_pos].rstrip() + f"\n- {text}\n" + content[insert_pos:]
            else:
                # Section doesn't exist — add it before Recent Deaths
                if "## Recent Deaths" in content:
                    content = content.replace("## Recent Deaths", f"## {section}\n- {text}\n\n## Recent Deaths")
                else:
                    content = content.rstrip() + f"\n\n## {section}\n- {text}\n"
            
            learnings_path.write_text(content)
            return f"Learning recorded in [{section}]."
        
        # Call the DCSS method
        method = getattr(dcss, method_name)
        
        if param_model == EmptyParams:
            result = method(*args, **kwargs)
        elif hasattr(params, 'direction') and hasattr(params, 'key'):
            # SlotDirectionParams or SlotOptionalDirectionParams
            if params.direction:
                result = method(params.key, params.direction, *args, **kwargs)
            else:
                result = method(params.key, *args, **kwargs)
        elif hasattr(params, 'direction'):
            # DirectionParams or SpellParams
            if hasattr(params, 'key'):
                # SpellParams
                if params.direction:
                    result = method(params.key, params.direction, *args, **kwargs)
                else:
                    result = method(params.key, *args, **kwargs)
            else:
                # DirectionParams
                result = method(params.direction, *args, **kwargs)
        elif hasattr(params, 'key'):
            # SlotParams or OptionalSlotParams
            result = method(params.key, *args, **kwargs)
        elif hasattr(params, 'radius'):
            # MapParams
            result = method(radius=params.radius, *args, **kwargs)
        elif hasattr(params, 'n'):
            # MessagesParams
            result = method(n=params.n, *args, **kwargs)
        elif hasattr(params, 'thought'):
            # OverlayParams
            result = method(params.thought, *args, **kwargs)
        elif hasattr(params, 'cause'):
            # DeathParams
            result = method(params.cause, *args, **kwargs)
        elif hasattr(params, 'species_key'):
            # StartGameParams
            result = method(params.species_key, params.background_key, params.weapon_key, *args, **kwargs)
        else:
            # Should not happen
            raise ValueError(f"Unknown parameter model: {param_model}")
        
        # Format result
        if isinstance(result, list):
            return "\n".join(result) if result else getattr(handler, '_default_msg', "Done.")
        elif result is None:
            return getattr(handler, '_default_msg', "Done.")
        else:
            return str(result)
    
    return handler


def build_tools(dcss: DCSSGame) -> List[Dict[str, Any]]:
    """Build provider-agnostic tool definitions.
    
    Returns a list of tool dicts with: name, description, parameters, handler.
    Each handler takes a dict of params and returns a string.
    """
    
    tools = []
    
    # --- State queries (free, no turn cost) ---
    
    tools.append({
        "name": "get_state_text",
        "description": "Get full game state: stats, messages, inventory, enemies, map. Use this to orient yourself.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "get_state_text", EmptyParams)
    })
    
    tools.append({
        "name": "get_map", 
        "description": "Get ASCII map centered on player (@). Radius controls view size.",
        "parameters": {
            "type": "object",
            "properties": {
                "radius": {"type": "integer", "description": "Map view radius", "default": 15}
            },
            "required": []
        },
        "handler": _make_handler(dcss, "get_map", MapParams)
    })
    
    tools.append({
        "name": "get_landmarks",
        "description": "Find stairs, altars, and other notable features on the explored map. Shows direction and distance from current position. Use this to navigate to known stairs instead of wandering.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": lambda params: dcss.get_landmarks()
    })
    
    tools.append({
        "name": "write_note",
        "description": "Write a note to your notepad. Notes are organized by page (default: current floor like 'D:1'). Use 'general' for cross-floor notes. Survives context compaction.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Note text"},
                "page": {"type": "string", "description": "Page name (default: current floor, e.g. 'D:1')", "default": ""}
            },
            "required": ["text"]
        },
        "handler": lambda params: dcss.write_note(params["text"], params.get("page", ""))
    })
    
    tools.append({
        "name": "read_notes",
        "description": "Read your notepad. Shows all pages by default, or specify a page name. Call after compaction to reorient.",
        "parameters": {
            "type": "object",
            "properties": {
                "page": {"type": "string", "description": "Page name to read (blank = all pages)", "default": ""}
            },
            "required": []
        },
        "handler": lambda params: dcss.read_notes(params.get("page", ""))
    })
    
    tools.append({
        "name": "rip_page",
        "description": "Remove a page from the notepad. Use when the notes are no longer relevant (e.g. fully cleared floor, bought everything from a shop).",
        "parameters": {
            "type": "object",
            "properties": {
                "page": {"type": "string", "description": "Page name to remove (e.g. 'D:1')"}
            },
            "required": ["page"]
        },
        "handler": lambda params: dcss.rip_page(params["page"])
    })
    
    tools.append({
        "name": "get_inventory",
        "description": "Get inventory as list of items with slot letters and names.",
        "parameters": {
            "type": "object", 
            "properties": {},
            "required": []
        },
        "handler": lambda params: json.dumps(dcss.get_inventory(), indent=2)
    })
    
    tools.append({
        "name": "get_nearby_enemies",
        "description": "Get nearby visible enemies sorted by distance, with direction and threat level.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": lambda params: json.dumps(dcss.get_nearby_enemies(), indent=2)
    })
    
    tools.append({
        "name": "get_stats",
        "description": "Get one-line stats summary: HP, MP, AC, EV, XL, place, turn.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "get_stats", EmptyParams)
    })
    
    tools.append({
        "name": "get_messages",
        "description": "Get last N game messages. Messages reveal what's happening in combat.",
        "parameters": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "Number of recent messages to return", "default": 10}
            },
            "required": []
        },
        "handler": lambda params: "\n".join(dcss.get_messages(n=params.get('n', 10)))
    })
    
    # --- Movement & exploration ---
    
    tools.append({
        "name": "move",
        "description": "Move one step in a direction. Moving into an enemy = melee attack.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "Direction: n/s/e/w/ne/nw/se/sw"}
            },
            "required": ["direction"]
        },
        "handler": _make_handler(dcss, "move", DirectionParams)
    })
    
    # Set default messages for handlers
    move_handler = tools[-1]["handler"]
    move_handler._default_msg = "Moved."
    
    tools.append({
        "name": "auto_explore",
        "description": "Auto-explore the current floor. Stops on enemies, items, or fully explored.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "auto_explore", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Exploring..."
    
    tools.append({
        "name": "auto_fight",
        "description": "Auto-fight nearest enemy (Tab). Blocked at low HP as Berserker — use attack() instead.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "auto_fight", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Fighting..."
    
    tools.append({
        "name": "rest",
        "description": "Rest until healed (5). Won't work with enemies nearby.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "rest", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Resting..."
    
    tools.append({
        "name": "wait_turn",
        "description": "Wait one turn in place.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "wait_turn", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Waited."
    
    tools.append({
        "name": "go_upstairs",
        "description": "Ascend to the previous floor. If not standing on stairs, auto-travels to the nearest upstairs first. May be interrupted by enemies.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "go_upstairs", EmptyParams)
    })
    
    tools.append({
        "name": "go_downstairs",
        "description": "Descend to the next floor. If not standing on stairs, auto-travels to the nearest downstairs first. May be interrupted by enemies.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "go_downstairs", EmptyParams)
    })
    
    # --- Items ---
    
    tools.append({
        "name": "pickup",
        "description": "Pick up items on the ground.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "pickup", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Picked up."
    
    tools.append({
        "name": "wield",
        "description": "Wield a weapon by inventory slot letter.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "wield", SlotParams)
    })
    tools[-1]["handler"]._default_msg = "Wielded."
    
    tools.append({
        "name": "wear",
        "description": "Wear armour by inventory slot letter.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "wear", SlotParams)
    })
    tools[-1]["handler"]._default_msg = "Wearing."
    
    tools.append({
        "name": "quaff",
        "description": "Drink a potion by inventory slot letter.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "quaff", SlotParams)
    })
    tools[-1]["handler"]._default_msg = "Quaffed."
    
    tools.append({
        "name": "read_scroll",
        "description": "Read a scroll by inventory slot letter.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "read_scroll", SlotParams)
    })
    tools[-1]["handler"]._default_msg = "Read scroll."
    
    tools.append({
        "name": "drop",
        "description": "Drop an item by inventory slot letter.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "drop", SlotParams)
    })
    tools[-1]["handler"]._default_msg = "Dropped."
    
    tools.append({
        "name": "zap_wand",
        "description": "Zap a wand by inventory slot letter, optionally in a direction.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"},
                "direction": {"type": "string", "description": "Direction: n/s/e/w/ne/nw/se/sw (optional)", "default": ""}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "zap_wand", SlotOptionalDirectionParams)
    })
    tools[-1]["handler"]._default_msg = "Zapped."
    
    tools.append({
        "name": "evoke",
        "description": "Evoke a miscellaneous evocable item by inventory slot letter.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "evoke", SlotParams)
    })
    tools[-1]["handler"]._default_msg = "Evoked."
    
    tools.append({
        "name": "throw_item",
        "description": "Throw/fire an item at an enemy. Requires slot letter and direction.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"},
                "direction": {"type": "string", "description": "Direction: n/s/e/w/ne/nw/se/sw"}
            },
            "required": ["key", "direction"]
        },
        "handler": _make_handler(dcss, "throw_item", SlotDirectionParams)
    })
    tools[-1]["handler"]._default_msg = "Thrown."
    
    tools.append({
        "name": "put_on_jewelry",
        "description": "Put on a ring or amulet by inventory slot letter.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "put_on_jewelry", SlotParams)
    })
    tools[-1]["handler"]._default_msg = "Put on."
    
    tools.append({
        "name": "remove_jewelry",
        "description": "Remove a ring or amulet. Slot letter optional if only one worn.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z), optional if only one worn", "default": ""}
            },
            "required": []
        },
        "handler": _make_handler(dcss, "remove_jewelry", OptionalSlotParams)
    })
    tools[-1]["handler"]._default_msg = "Removed."
    
    tools.append({
        "name": "take_off_armour",
        "description": "Take off worn armour by inventory slot letter.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "take_off_armour", SlotParams)
    })
    tools[-1]["handler"]._default_msg = "Taken off."
    
    tools.append({
        "name": "examine",
        "description": "Examine/describe an inventory item by slot letter. Shows stats and details.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "examine", SlotParams)
    })
    tools[-1]["handler"]._default_msg = "No description."
    
    # --- Combat & abilities ---
    
    tools.append({
        "name": "use_ability",
        "description": "Use a god/species ability by key. a=Berserk, b=Trog's Hand, c=Brothers in Arms.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Ability key (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "use_ability", SlotParams)
    })
    tools[-1]["handler"]._default_msg = "Used ability."
    
    tools.append({
        "name": "cast_spell",
        "description": "Cast a spell by key, optionally in a direction.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Spell slot letter"},
                "direction": {"type": "string", "description": "Direction to cast: n/s/e/w/ne/nw/se/sw (optional)", "default": ""}
            },
            "required": ["key"]
        },
        "handler": _make_handler(dcss, "cast_spell", SpellParams)
    })
    tools[-1]["handler"]._default_msg = "Cast spell."
    
    tools.append({
        "name": "pray",
        "description": "Pray at an altar.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "pray", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Prayed."
    
    # --- Interface ---
    
    tools.append({
        "name": "respond",
        "description": "Respond to a game prompt. action: 'yes' (confirm), 'no' (deny), or 'escape' (cancel).",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "yes / no / escape"}
            },
            "required": ["action"]
        },
        "handler": lambda params: dcss.respond(params["action"])
    })

    tools.append({
        "name": "choose_stat",
        "description": "Choose which stat to increase on level up. Called when you see 'Increase (S)trength, (I)ntelligence, or (D)exterity?'. Pick based on your build: melee→s, caster→i, hybrid→depends.",
        "parameters": {
            "type": "object",
            "properties": {
                "stat": {"type": "string", "description": "s (Strength), i (Intelligence), or d (Dexterity)"}
            },
            "required": ["stat"]
        },
        "handler": lambda params: dcss.choose_stat(params["stat"])
    })
    
    # --- Overlay & stats ---
    
    # --- UI interaction ---

    tools.append({
        "name": "read_ui",
        "description": (
            "Read the currently open UI element (menu or popup). Returns title, items, "
            "and content. Works for shops, spell lists, item descriptions, god info, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": lambda params: dcss.read_ui()
    })

    tools.append({
        "name": "select_menu_item",
        "description": (
            "Press a hotkey letter in the current menu to select/toggle an item. "
            "For shops: press letter to toggle selection, then Enter to confirm purchase. "
            "For other menus: press the letter to choose that option."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The hotkey letter to press (e.g. 'a', 'b', 'Enter')"}
            },
            "required": ["key"]
        },
        "handler": lambda params: dcss.select_menu_item(params["key"])
    })

    tools.append({
        "name": "dismiss",
        "description": "Dismiss/close the current UI element (menu or popup) by pressing Escape.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": lambda params: dcss.dismiss()
    })

    tools.append({
        "name": "update_overlay",
        "description": "Update the stream overlay with current stats and your thought. Call after every action.",
        "parameters": {
            "type": "object",
            "properties": {
                "thought": {"type": "string", "description": "Brief one-liner about what you're thinking (shown to stream viewers)", "default": ""}
            },
            "required": []
        },
        "handler": lambda params: (dcss.update_overlay(params.get('thought', '')), "Overlay updated.")[1]
    })
    
    tools.append({
        "name": "new_attempt",
        "description": "Start a new game attempt. Call before start_game. Increments attempt counter on overlay.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": lambda params: (dcss.new_attempt(), f"Attempt #{dcss._attempt} started.")[1]
    })
    
    tools.append({
        "name": "record_death",
        "description": "Record a death. Call when you die. Increments death counter.",
        "parameters": {
            "type": "object",
            "properties": {
                "cause": {"type": "string", "description": "Brief cause of death", "default": ""}
            },
            "required": []
        },
        "handler": lambda params: (dcss.record_death(params.get('cause', '')), f"Death #{dcss._deaths} recorded.")[1]
    })
    
    tools.append({
        "name": "record_win",
        "description": "Record a win. Call when you escape with the Orb.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": lambda params: (dcss.record_win(), f"Win #{dcss._wins} recorded!")[1]
    })
    
    # --- Learnings ---
    
    tools.append({
        "name": "write_learning",
        "description": "Record a lesson to learnings.md under a tier. Call during gameplay, after death, AND after wins. Be specific. Include [situation: ...] tags when the learning is context-dependent. Example: '- Don't berserk when surrounded [situation: 3+ enemies, no corridor, post-berserk exhaustion = death]'. These persist across all future games.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "A lesson learned. Be specific and actionable. Include [situation: ...] tags when context-dependent."},
                "section": {"type": "string", "description": "Tier: Hard Rules, Heuristics, Notes, Melee Builds, Caster Builds, Species Notes, or a new one", "default": "Heuristics"}
            },
            "required": ["text"]
        },
        "handler": _make_handler(dcss, "write_learning", LearningParams)
    })
    
    # --- Narration ---
    
    tools.append({
        "name": "narrate",
        "description": "Share your thoughts with stream viewers. MUST be called at least once every 5 actions. Think out loud: what do you see, what's your plan, what worries you, what excites you.",
        "parameters": {
            "type": "object",
            "properties": {
                "thought": {"type": "string", "description": "Your inner monologue for viewers. Be natural, opinionated, and conversational. 2-3 sentences."}
            },
            "required": ["thought"]
        },
        "handler": lambda params: (write_monologue(params.get('thought', '')), setattr(dcss, '_actions_since_narrate', 0), sys.stdout.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')},{int(time.time()*1000)%1000:03d} 💭 {params.get('thought', '')}\n"), sys.stdout.flush(), "[Narrated]")[4]
    })
    
    # --- Death Journal ---
    
    def _record_death_journal(params_dict: Dict[str, Any]) -> str:
        params = DeathJournalParams(**params_dict)
        learnings_path = Path(__file__).parent.parent / "learnings.md"
        content = learnings_path.read_text() if learnings_path.exists() else ""
        
        # Count existing deaths
        import re
        existing_deaths = len(re.findall(r'### Death #\d+', content))
        death_num = existing_deaths + 1
        
        # Pull game state
        try:
            stats = dcss.get_stats()
        except Exception:
            stats = "unknown"
        
        place = getattr(dcss, '_place', 'unknown')
        species = getattr(dcss, '_species', 'unknown')
        turn = getattr(dcss, '_turn', '?')
        hp = getattr(dcss, '_hp', '?')
        max_hp = getattr(dcss, '_max_hp', '?')
        
        try:
            enemies = dcss.get_nearby_enemies()
            if isinstance(enemies, list):
                enemy_names = [e.get('name', str(e)) for e in enemies[:5]] if enemies else ['none']
            else:
                enemy_names = [str(enemies)] if enemies else ['none']
        except Exception:
            enemy_names = ['unknown']
        
        try:
            inventory = dcss.get_inventory()
            if isinstance(inventory, list):
                inv_highlights = [item.get('name', str(item)) for item in inventory[:8]]
            else:
                inv_highlights = [str(inventory)] if inventory else ['none']
        except Exception:
            inv_highlights = ['unknown']
        
        entry = (
            f"\n### Death #{death_num}: {place}, {species}, Turn {turn}\n"
            f"- Cause: {params.cause}\n"
            f"- HP when died: {hp}/{max_hp}\n"
            f"- Nearby enemies: {', '.join(enemy_names)}\n"
            f"- Inventory highlights: {', '.join(inv_highlights)}\n"
            f"- What could have helped: {params.reflection}\n"
        )
        
        # Insert into Death Journal section
        if "## Death Journal" in content:
            idx = content.index("## Death Journal")
            rest = content[idx + len("## Death Journal"):]
            # Remove the "(no deaths recorded yet)" placeholder if present
            rest = rest.replace("\n(no deaths recorded yet)", "")
            content = content[:idx] + "## Death Journal" + rest.rstrip() + "\n" + entry
        else:
            content = content.rstrip() + "\n\n## Death Journal\n" + entry
        
        learnings_path.write_text(content)
        return f"Death #{death_num} recorded in journal."
    
    tools.append({
        "name": "record_death_journal",
        "description": "Record structured death context to the Death Journal in learnings.md. Call after dying, alongside record_death(). Auto-pulls game state (place, species, turn, HP, enemies, inventory).",
        "parameters": {
            "type": "object",
            "properties": {
                "cause": {"type": "string", "description": "Brief cause of death from game messages"},
                "reflection": {"type": "string", "description": "What could have helped — your reflection on this death"}
            },
            "required": ["cause", "reflection"]
        },
        "handler": _record_death_journal
    })
    
    # --- Game lifecycle ---
    
    tools.append({
        "name": "start_game",
        "description": "Start a new DCSS game. Default: Minotaur Berserker (species=b, bg=f, weapon=b). Abandons any existing save first.",
        "parameters": {
            "type": "object",
            "properties": {
                "species_key": {"type": "string", "description": (
                    "Species key (0.34): a=Gnoll, b=Minotaur, c=Merfolk, d=Gargoyle, "
                    "e=Mountain Dwarf, f=Draconian, g=Troll, h=Deep Elf, i=Armataur, "
                    "j=Human, k=Kobold, l=Revenant, m=Demonspawn, n=Djinni, o=Spriggan, "
                    "p=Tengu, q=Oni, r=Barachi, s=Coglin, t=Vine Stalker, u=Poltergeist, "
                    "v=Demigod, w=Formicid, x=Naga, y=Octopode, z=Felid, A=Mummy"
                ), "default": "b"},
                "background_key": {"type": "string", "description": (
                    "Background key (0.34): a=Fighter, b=Gladiator, c=Monk, d=Hunter, "
                    "e=Brigand, f=Berserker, g=Cinder Acolyte, h=Chaos Knight, "
                    "i=Artificer, j=Shapeshifter, k=Wanderer, l=Delver, m=Warper, "
                    "n=Hexslinger, o=Enchanter, p=Reaver, q=Hedge Wizard, r=Conjurer, "
                    "s=Summoner, t=Necromancer, u=Forgewright, v=Fire Elementalist, "
                    "w=Ice Elementalist, x=Air Elementalist, y=Earth Elementalist, z=Alchemist"
                ), "default": "f"},
                "weapon_key": {"type": "string", "description": "Weapon key if prompted (a/b/etc, leave empty for auto)", "default": ""}
            },
            "required": []
        },
        "handler": _make_handler(dcss, "start_game", StartGameParams)
    })
    
    return tools