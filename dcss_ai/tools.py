#!/usr/bin/env python3
"""DCSS game tools - provider-agnostic tool definitions."""

import json
from pathlib import Path
from typing import Any, Dict, List, Callable
from pydantic import BaseModel, Field

from dcss_ai.game import DCSSGame


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

class LearningParams(BaseModel):
    text: str = Field(description="A lesson learned from this game. Be specific and actionable.")

class StartGameParams(BaseModel):
    species_key: str = Field(default="r", description=(
        "Species key: a=Armataur, b=Barachi, c=Coglin, d=Demigod, e=Djinni, "
        "f=Draconian, g=Deep Elf, h=Felid, i=Formicid, j=Gargoyle, k=Ghoul, "
        "l=Gnoll, m=Grotesk, n=Hill Orc, o=Human, p=Kobold, q=Merfolk, "
        "r=Minotaur, s=Mummy, t=Naga, u=Octopode, v=Oni, w=Spriggan, "
        "x=Tengu, y=Troll, z=Vampire, A=Vine Stalker"
    ))
    background_key: str = Field(default="a", description=(
        "Background key: a=Berserker, b=Cinder Acolyte, c=Conjurer, "
        "d=Enchanter, e=Fighter, f=Gladiator, g=Hexslinger, h=Hunter, "
        "i=Ice Elementalist, j=Delver, k=Warper, l=Necromancer, "
        "m=Summoner, n=Transmuter, o=Fire Elementalist, p=Air Elementalist, "
        "q=Earth Elementalist, r=Alchemist, s=Shapeshifter, t=Wanderer, "
        "u=Monk, v=Brigand"
    ))
    weapon_key: str = Field(default="b", description="Weapon key (a or b, depends on background)")

class MapParams(BaseModel):
    radius: int = Field(default=7, description="Map view radius")

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
            with open(learnings_path, 'a') as f:
                f.write(f"\n- {params.text}")
            return "Learning recorded."
        
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
                "radius": {"type": "integer", "description": "Map view radius", "default": 7}
            },
            "required": []
        },
        "handler": _make_handler(dcss, "get_map", MapParams)
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
        "description": "Go upstairs (<).",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "go_upstairs", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Went upstairs."
    
    tools.append({
        "name": "go_downstairs",
        "description": "Go downstairs (>).",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "go_downstairs", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Went downstairs."
    
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
        "name": "attack",
        "description": "Melee attack in a direction. Use when auto_fight is blocked at low HP.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "Direction: n/s/e/w/ne/nw/se/sw"}
            },
            "required": ["direction"]
        },
        "handler": _make_handler(dcss, "attack", DirectionParams)
    })
    tools[-1]["handler"]._default_msg = "Attacked."
    
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
        "name": "confirm",
        "description": "Confirm a prompt (Y).",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "confirm", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Confirmed."
    
    tools.append({
        "name": "deny",
        "description": "Deny a prompt (N).",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "deny", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Denied."
    
    tools.append({
        "name": "escape",
        "description": "Press Escape to cancel.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "handler": _make_handler(dcss, "escape", EmptyParams)
    })
    tools[-1]["handler"]._default_msg = "Escaped."
    
    # --- Overlay & stats ---
    
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
        "description": "Append a lesson to learnings.md. Call after every death AND every win. Be specific: what happened, why, what to do differently. These persist across all future games.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "A lesson learned from this game. Be specific and actionable."}
            },
            "required": ["text"]
        },
        "handler": _make_handler(dcss, "write_learning", LearningParams)
    })
    
    # --- Game lifecycle ---
    
    tools.append({
        "name": "start_game",
        "description": "Start a new DCSS game. Default: Minotaur Berserker (species=b, bg=f, weapon=b). Abandons any existing save first.",
        "parameters": {
            "type": "object",
            "properties": {
                "species_key": {"type": "string", "description": (
                    "Species key: a=Armataur, b=Barachi, c=Coglin, d=Demigod, e=Djinni, "
                    "f=Draconian, g=Deep Elf, h=Felid, i=Formicid, j=Gargoyle, k=Ghoul, "
                    "l=Gnoll, m=Grotesk, n=Hill Orc, o=Human, p=Kobold, q=Merfolk, "
                    "r=Minotaur, s=Mummy, t=Naga, u=Octopode, v=Oni, w=Spriggan, "
                    "x=Tengu, y=Troll, z=Vampire, A=Vine Stalker"
                ), "default": "r"},
                "background_key": {"type": "string", "description": (
                    "Background key: a=Berserker, b=Cinder Acolyte, c=Conjurer, "
                    "d=Enchanter, e=Fighter, f=Gladiator, g=Hexslinger, h=Hunter, "
                    "i=Ice Elementalist, j=Delver, k=Warper, l=Necromancer, "
                    "m=Summoner, n=Transmuter, o=Fire Elementalist, p=Air Elementalist, "
                    "q=Earth Elementalist, r=Alchemist, s=Shapeshifter, t=Wanderer, "
                    "u=Monk, v=Brigand"
                ), "default": "a"},
                "weapon_key": {"type": "string", "description": "Weapon key (a or b, depends on background)", "default": "b"}
            },
            "required": []
        },
        "handler": _make_handler(dcss, "start_game", StartGameParams)
    })
    
    return tools