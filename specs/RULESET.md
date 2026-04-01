# UnoArena — Official Ruleset

This document defines the complete, authoritative ruleset for the UnoArena platform. All game logic, event definitions, and domain models must conform to these rules.

---

## 1. Card Set

Standard UNO deck only. No blank or customizable cards are used.

| Category | Cards |
|---|---|
| Number cards | One 0 and two each of 1–9, in each of 4 colors = **76 cards** |
| Skip | 2 per color = **8 cards** |
| Reverse | 2 per color = **8 cards** |
| Draw Two (+2) | 2 per color = **8 cards** |
| Wild | **4 cards** (colorless) |
| Wild Draw Four (+4) | **4 cards** (colorless) |
| **Total** | **108 cards** |

Colors: Red, Green, Blue, Yellow.

Wild and Wild Draw Four cards have no inherent color.

---

## 2. Setup

1. Shuffle all 108 cards.
2. Deal **7 cards** face-down to each player. Cards are private — no player may view another's hand.
3. Place the remaining cards face-down as the **draw pile**.
4. Reveal the top card of the draw pile to start the **discard pile**:
   - If the revealed card is a number card (0–9), it becomes the starting card.
   - If it is any other card type (Skip, Reverse, Draw Two, Wild, Wild Draw Four), place it at the **bottom** of the draw pile and reveal the next card. Repeat until a number card is found.
5. Play begins with the player to the **left of the dealer** and proceeds **clockwise**.

---

## 3. Taking a Turn

On their turn, a player must do exactly one of the following:

**Option A — Play a card**: Place one card from their hand onto the discard pile. The card must be a legal play (see Section 3.1).

**Option B — Draw**: Draw one card from the draw pile. The player's turn ends immediately after drawing; the drawn card may not be played that turn.

### 3.1 Legal Play

A card is legal to play if it matches the top card of the discard pile in at least one of:
- **Color** (e.g., any Blue card on a Blue card), or
- **Number or Symbol** (e.g., a Red Skip on a Blue Skip, a Green 7 on a Red 7).

Wild and Wild Draw Four cards may be played on top of **any** card regardless of color.

---

## 4. Special Cards

### 4.1 Reverse

- Switches the direction of play: clockwise becomes counterclockwise and vice versa.
- May be played on a card of matching color or on another Reverse card.
- **If the starting card of the game**: play begins counterclockwise instead of clockwise.

### 4.2 Skip

- The next player in turn order loses their entire turn.
- May be played on a card of matching color or on another Skip card.
- **If the starting card of the game**: the first player's turn is skipped; the second player goes first.

### 4.3 Draw Two (+2)

- The next player in turn order must draw two cards and their turn is skipped.
- May be played on a card of matching color or on another Draw Two card.
- **If the starting card of the game**: the first player draws two cards and their turn is skipped.
- **Stacking applies** — see Section 5.

### 4.4 Wild

- May be played on top of any card.
- The player who plays it declares the **active color** going forward. The Wild is then treated as if it had that color.
- **If the starting card of the game**: the first player to take a turn declares the active color before playing.

### 4.5 Wild Draw Four (+4)

- May be played on top of any card.
- The player declares the active color going forward.
- The next player in turn order must draw four cards and their turn is skipped.
- **Legal condition**: A Wild Draw Four may only be played legally if the player holds **no cards matching the current active color** in their hand. Wild cards in hand do **not** count as a matching color.
- **If the starting card of the game**: shuffle it back into the draw pile (not to the bottom — reshuffle) and reveal a new top card. Repeat if necessary.
- **Cannot be stacked** in any form — see Section 5.
- **May be challenged** — see Section 6.

---

## 5. Draw Two Stacking

Draw Two stacking is **enabled**. Wild Draw Four stacking is **disabled** in all forms.

### Rules

- When a Draw Two is played, the next player in turn order may respond by playing one of their own Draw Two cards instead of drawing the penalty.
- Doing so **passes and accumulates** the penalty: each Draw Two added increases the total by 2 (2 → 4 → 6 → 8 → ...).
- The chain continues as long as each successive player plays a Draw Two on their turn.
- The first player in the chain who **cannot or chooses not** to play a Draw Two must draw the full accumulated total and their turn is skipped.

### What May Not Be Stacked

- A **Wild Draw Four** may not be played in response to a Draw Two to extend or absorb a stack.
- A Wild Draw Four may not be played in response to another Wild Draw Four.

### Jump-In Interaction with Stacking

- A player may jump in (Section 7) with the **exact same Draw Two** that is on top of the discard pile during an active stack chain.
- The jump-in also counts as a stack response: the penalty accumulates by 2 and the turn continues from the jumping-in player.
- The player who was originally next in turn order (the intended victim before the jump-in) is skipped.

---

## 6. Wild Draw Four Challenge

### Who May Challenge

Only the **player required to draw the four cards** (the next player in turn order) may initiate a challenge. No other player may challenge.

### Process

1. The challenger must declare the challenge **within 5 seconds** of the Wild Draw Four being played, and **before drawing any cards**. The challenge window closes when the 5-second timer expires or the player begins drawing, whichever comes first.
2. The player who played the Wild Draw Four must **reveal their entire hand** to the challenger.

### Outcomes

| Outcome | What happened | Consequence |
|---|---|---|
| **Successful challenge (guilty)** | The player had at least one card matching the current active color | The Wild Draw Four is **rescinded**. The player who played it draws **4 cards**. The challenger does **not** draw any cards and takes their turn normally. |
| **Unsuccessful challenge (innocent)** | The player had no cards matching the current active color | The Wild Draw Four stands. The challenger draws **6 cards** (4 from the +4 effect plus 2 penalty) and their turn is skipped. |

### Notes

- Wild cards in the player's hand do **not** count as a matching color when determining guilt.
- If no challenge is issued, the Wild Draw Four effect resolves normally (next player draws 4 and is skipped).
- **Timing**: the 5-second challenge window runs **before** the next player's 45-second turn timer begins. The player must decide to challenge or draw within this window. The 45-second timer only starts after the challenge is resolved or the player draws. This window is separate from and sequential to the Uno! challenge window (see Section 8).

---

## 7. Jump-In Rule

Jump-in is an **active rule** on this platform.

### Eligibility

- A player may play out of turn if they hold a card **identical** to the most recently played card in both **color and rank/symbol**.
- Jump-in is allowed on: number cards, Skip cards, Reverse cards, and Draw Two cards.
- Jump-in is **not allowed** on Wild cards or Wild Draw Four cards (they have no inherent color and cannot be matched exactly).

### Effects

- The jumping-in player immediately places their matching card on the discard pile.
- **Turn order resets from the jumper**: play continues from the jumping-in player's position, proceeding in the current direction of play. All players between the original player and the jumper are skipped for that turn cycle.
- The card played by the jumper takes full effect (e.g., a Skip forces the next player after the jumper to skip; a Reverse changes direction from the jumper's position; a Draw Two initiates or extends a stack).
- **Double Reverse**: if a Reverse is in play and a player jumps in with the identical Reverse, the direction reverses twice, returning to the original direction of play.

### Draw Two Jump-In During a Stack

- If a Draw Two stack chain is active and a player holds the exact same Draw Two on top of the discard pile, they may jump in.
- The jump-in extends the stack: the accumulated penalty increases by 2 and turn order continues from the jumper.
- The player who was next in turn order before the jump-in is skipped.

### Simultaneous Jump-Ins

- If two or more players attempt to jump in with the same card simultaneously, the **first valid submission received** by the server wins.
- All other simultaneous submissions are rejected with a conflict response.

### Self-Jump

- A player may **not** jump in on their own card. Playing two identical cards in the same turn is not allowed.

---

## 8. Calling "Uno!"

- A player **must** call "Uno!" at the moment they play their second-to-last card, leaving exactly one card in their hand.
- The call must occur as part of, or immediately following, the card play action.

### Challenge Window

- The moment a player plays their second-to-last card, a **5-second challenge window** opens.
- During this window, **any opponent** may challenge whether the player called "Uno!".
- The window closes early the moment the next player begins their turn (i.e., submits any game action: playing a card, drawing, challenging, or jumping in).
- **Concurrency**: if multiple opponents attempt to challenge simultaneously, only the **first valid challenge received by the server** is processed. All others are rejected.
- **Timing**: the 5-second Uno! challenge window runs **within** the next player's 45-second turn timer. The turn timer starts immediately when the next player's turn begins; the Uno! window does not pause it.
- **When Wild Draw Four is also in play**: if the second-to-last card played was a Wild Draw Four, the Uno! challenge window (5 seconds, open to all opponents) runs **first**. After the Uno! window closes, the next player's turn begins with a separate Wild Draw Four challenge window (5 seconds — see Section 6). The 45-second turn timer only starts after the Wild Draw Four window resolves.

### Outcomes

- If the challenged player **did not** call "Uno!" (guilty): they draw **2 penalty cards**. The challenger is not penalized.
- If the challenged player **did** correctly call "Uno!" (innocent): the **challenger** draws **2 penalty cards**.
- If the window expires with no challenge, the player retains their one-card hand with no penalty.

---

## 9. Winning a Round

- A player wins the round the moment they play their last card and hold **zero cards**.
- The winner scores points equal to the **sum of all cards remaining in every other player's hand**:

| Card type | Point value |
|---|---|
| Number cards (0–9) | Face value (0–9 points) |
| Skip | 20 points |
| Reverse | 20 points |
| Draw Two | 20 points |
| Wild | 50 points |
| Wild Draw Four | 50 points |

---

## 10. Winning the Game

- A game is played across **multiple rounds**.
- The first player to accumulate a **cumulative score of 500 or more points** wins the game.
- After each round ends, all cards are collected, reshuffled, and a new round begins with the same players.

---

## 11. Draw Pile Exhaustion

- If a player must draw and the draw pile is empty:
  1. Take all cards from the discard pile **except the top card**.
  2. Shuffle those cards to form a new draw pile.
  3. The top card of the discard pile remains in place; play continues normally.

---

## 12. Turn Order Reference

| Event | Effect on turn order |
|---|---|
| Normal play | Advances to next player in current direction |
| Reverse played | Direction flips; next player is now in the opposite direction |
| Skip played | Next player in current direction loses their turn |
| Draw Two played (no stack) | Next player draws 2 and is skipped |
| Draw Two stacked | Penalty accumulates; chain continues; eventual victim draws total and is skipped |
| Wild Draw Four played | Next player draws 4 and is skipped |
| Jump-in occurs | Turn order resets from the jumper; proceeding in current direction |
| Jump-in with Reverse | Direction flips from jumper's position |
| Jump-in with Draw Two (during stack) | Penalty +2, turn continues from jumper; original next player skipped |
| Double Reverse via jump-in | Direction reverses twice; original direction restored |
