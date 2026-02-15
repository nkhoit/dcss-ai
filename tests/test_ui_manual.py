#!/usr/bin/env python3
"""Manual smoke test for menu/popup/UI tools.

Usage: python -m tests.test_ui_manual --username dcssai --password dcssai

Starts a game, walks around, and tests UI interactions.
"""
import argparse
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dcss_ai.game import DCSSGame

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8080/socket")
    parser.add_argument("--username", default="dcssai")
    parser.add_argument("--password", default="dcssai")
    args = parser.parse_args()

    dcss = DCSSGame()
    print(f"Connecting to {args.url}...")
    if not dcss.connect(args.url, args.username, args.password):
        print("FAIL: Could not connect")
        return 1

    print("Starting game (Minotaur Berserker)...")
    result = dcss.start_game("r", "a")
    print(f"  start_game: {result[:200]}...")

    # Test 1: read_ui with nothing open
    print("\n=== Test 1: read_ui (nothing open) ===")
    r = dcss.read_ui()
    print(f"  {r}")
    assert "No menu or popup" in r, f"Expected no UI, got: {r}"
    print("  PASS")

    # Test 2: dismiss with nothing open
    print("\n=== Test 2: dismiss (nothing open) ===")
    r = dcss.dismiss()
    print(f"  {r}")
    print("  PASS")

    # Test 3: Open inventory (i) — this is a menu
    print("\n=== Test 3: Inventory menu ===")
    msgs = dcss._act("i")
    print(f"  _act('i') returned {len(msgs)} messages")
    print(f"  Menu cached: {dcss._current_menu is not None}")
    if dcss._current_menu:
        r = dcss.read_ui()
        print(f"  read_ui():\n{r[:500]}")
        # Dismiss it
        r = dcss.dismiss()
        print(f"  dismiss(): {r}")
    else:
        print("  WARN: No menu opened from 'i' — checking popup")
        if dcss._current_popup:
            r = dcss.read_ui()
            print(f"  read_ui() (popup):\n{r[:500]}")
            r = dcss.dismiss()
            print(f"  dismiss(): {r}")
        else:
            print("  WARN: Neither menu nor popup opened")

    # Test 4: Open spell list (I for memorized spells... MiBe has none)
    # Instead try ability menu (a)
    print("\n=== Test 4: Ability menu ===")
    msgs = dcss._act("a")
    print(f"  _act('a') returned {len(msgs)} messages")
    print(f"  Menu cached: {dcss._current_menu is not None}")
    if dcss._current_menu:
        r = dcss.read_ui()
        print(f"  read_ui():\n{r[:500]}")
        r = dcss.dismiss()
        print(f"  dismiss(): {r}")
    else:
        print("  WARN: No menu from ability key")

    # Test 5: Try examine (x + look at something) — this opens a popup
    print("\n=== Test 5: Examine mode ===")
    # 'x' enters targeting/examine mode, '.' or Enter examines current tile
    # This might not open a popup but let's try '\\' for known items list
    msgs = dcss._act("\\")
    print(f"  _act('\\\\') returned {len(msgs)} messages")
    print(f"  Menu cached: {dcss._current_menu is not None}")
    print(f"  Popup cached: {dcss._current_popup is not None}")
    if dcss._current_menu or dcss._current_popup:
        r = dcss.read_ui()
        print(f"  read_ui():\n{r[:500]}")
        r = dcss.dismiss()
        print(f"  dismiss(): {r}")

    # Test 6: respond tool
    print("\n=== Test 6: respond ===")
    # Can't easily trigger a prompt, but test the method doesn't crash
    r = dcss.respond("escape")
    print(f"  respond('escape'): {len(r)} messages")
    print("  PASS")

    # Test 7: select_menu_item with no menu
    print("\n=== Test 7: select_menu_item (no menu) ===")
    r = dcss.select_menu_item("a")
    print(f"  {r}")
    assert "No menu" in r, f"Expected no menu msg, got: {r}"
    print("  PASS")

    # Test 8: Walk around and auto-explore a bit
    print("\n=== Test 8: Auto-explore (brief) ===")
    msgs = dcss.auto_explore()
    print(f"  auto_explore: {len(msgs)} messages")
    state = dcss.get_stats()
    print(f"  Stats: {state[:200] if isinstance(state, str) else state}")
    print("  PASS")

    # Quit cleanly
    print("\n=== Cleanup: quit ===")
    dcss.quit_game()
    dcss.disconnect()
    print("All tests passed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
