#!/usr/bin/env python3
"""DCSS game tools - provider-agnostic tool definitions."""

import json
import os
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


def _make_handler(dcss: DCSSGame, method_name: str, param_model: type, *args, **kwargs) -> Callable:
    """Create a handler function that validates params and calls a DCSS method."""
    def handler(params_dict: Dict[str, Any]) -> str:
        # Validate parameters using Pydantic model
        params = param_model(**params_dict)
        
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


def _use_item_handler(dcss: DCSSGame, key: str) -> str:
    """Smart item handler that routes to the appropriate action based on item type.
    
    Uses base_type from raw DCSS inventory data for reliable type detection.
    DCSS base_type: 0=weapon, 1=missile, 2=armour, 3=wand, 5=scroll,
                    6=jewellery, 7=potion, 8=book, 9=staff, 10=orb, 11=misc
    """
    try:
        # Convert slot letter to numeric index
        if len(key) == 1 and key.isalpha():
            slot_idx = ord(key.lower()) - ord('a')
        else:
            return f"Invalid slot key '{key}'."
        
        # Get raw inventory data (has base_type)
        raw_item = dcss._inventory.get(slot_idx)
        if not raw_item:
            return f"No item in slot {key}."
        
        item_name = raw_item.get("name", "unknown")
        base_type = raw_item.get("base_type")
        equipped = raw_item.get("equipped")
        
        # Route by base_type (reliable)
        if base_type == 0:  # weapon
            return dcss.wield(key)
        elif base_type == 9:  # staff (wieldable)
            return dcss.wield(key)
        elif base_type == 2:  # armour
            if equipped:
                return f"{item_name} is already equipped. Use unequip('{key}') to take it off."
            return dcss.wear(key)
        elif base_type == 7:  # potion
            return dcss.quaff(key)
        elif base_type == 5:  # scroll
            return dcss.read_scroll(key)
        elif base_type == 6:  # jewellery
            if equipped:
                return f"{item_name} is already equipped. Use unequip('{key}') to remove it."
            return dcss.put_on_jewelry(key)
        elif base_type == 3:  # wand
            return dcss.evoke(key)
        elif base_type == 11:  # misc evocable
            return dcss.evoke(key)
        elif base_type is not None:
            return f"Can't use {item_name} (type {base_type}) directly. Try examine('{key}') for details."
        
        # Fallback: name-based detection if base_type missing
        name_lower = item_name.lower()
        if "potion" in name_lower:
            return dcss.quaff(key)
        elif "scroll" in name_lower:
            return dcss.read_scroll(key)
        elif "wand" in name_lower:
            return dcss.evoke(key)
        
        return f"Unknown item type '{item_name}' - use examine('{key}') for details."
        
    except Exception as e:
        return f"Error using item: {str(e)}"


def build_tools(dcss: DCSSGame) -> List[Dict[str, Any]]:
    """Build provider-agnostic tool definitions.
    
    Returns a list of tool dicts with: name, description, parameters, handler.
    Each handler takes a dict of params and returns a string.
    """
    
    tools = []
    
    # --- State queries (free, no turn cost) ---
    
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
        "name": "use_item",
        "description": "Use an item from inventory by slot letter. Automatically determines the appropriate action: wield weapons, wear armour, quaff potions, read scrolls, evoke misc items, put on jewelry, remove jewelry, or take off armour.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": lambda params: _use_item_handler(dcss, params["key"])
    })
    
    tools.append({
        "name": "drop_item",
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
    
    def _unequip_handler(params_dict):
        key = params_dict.get("key", "")
        if len(key) == 1 and key.isalpha():
            slot_idx = ord(key.lower()) - ord('a')
        else:
            return f"Invalid slot key '{key}'."
        raw_item = dcss._inventory.get(slot_idx)
        if not raw_item:
            return f"No item in slot {key}."
        if not raw_item.get("equipped"):
            return f"{raw_item.get('name', 'Item')} is not equipped."
        base_type = raw_item.get("base_type")
        if base_type == 2:  # armour
            return dcss.take_off_armour(key)
        elif base_type == 6:  # jewellery
            return dcss.remove_jewelry(key)
        elif base_type in (0, 9):  # weapon/staff — unwield by wielding bare hands
            return dcss.wield("-")  # '-' for bare hands
        return f"Can't unequip {raw_item.get('name', 'item')}."

    tools.append({
        "name": "unequip",
        "description": "Take off or unwield an equipped item by slot letter. Use when swapping gear.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Inventory slot letter (a-z)"}
            },
            "required": ["key"]
        },
        "handler": _unequip_handler
    })
    
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
        "name": "record_win",
        "description": "Record a win. Call when you escape with the Orb.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": lambda params: (dcss.record_win(), f"Win #{dcss._wins} recorded!")[1]
    })
    
    # --- Narration ---
    
    narrate_interval = int(os.environ.get("DCSS_NARRATE_INTERVAL", "5"))
    if narrate_interval > 0:
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