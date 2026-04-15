# Tool reference (shared across agents)

Return exactly one action object `{"tool": "<name>", "params": {...}}`.

## Combat (state_type: monster / elite / boss)
- `play_card` — `{"card_index": int, "target": "ENEMY_ID"?}` target required for single-target attacks.
- `end_turn` — `{}`
- `use_potion` — `{"slot": int, "target": "ENEMY_ID"?}`
- `discard_potion` — `{"slot": int}`

## In-combat hand selection (state_type: hand_select)
- `combat_select_card` — `{"card_index": int}`
- `combat_confirm` — `{}`

## Rewards (state_type: rewards)
- `claim_reward` — `{"index": int}` claim a reward (gold, card, relic, potion)
- `proceed` — `{}` leave rewards screen

## Card reward (state_type: card_reward)
- `pick_card_reward` — `{"card_index": int}`
- `skip_card_reward` — `{}`

## Map (state_type: map)
- `choose_map_node` — `{"index": int}` picks one of `map.next_options`

## Rest site (state_type: rest_site)
- `choose_rest` — `{"index": int}` (rest / smith / etc.)
- `proceed` — `{}`

## Shop (state_type: shop or fake_merchant)
- `shop_purchase` — `{"index": int}`
- `proceed` — `{}` leave when done

## Event (state_type: event)
- `choose_event` — `{"index": int}`
- `advance_dialogue` — `{}` click through ancient dialogues

## Deck overlays (state_type: card_select)
- `select_card` — `{"index": int}`
- `confirm_selection` — `{}`
- `cancel_selection` — `{}`

## Bundle (state_type: bundle_select)
- `select_bundle` — `{"index": int}`
- `confirm_bundle` — `{}`
- `cancel_bundle` — `{}`

## Relic (state_type: relic_select)
- `select_relic` — `{"index": int}`
- `skip_relic` — `{}`

## Treasure (state_type: treasure)
- `claim_treasure` — `{"index": int}`
- `proceed` — `{}`

## Crystal sphere (state_type: crystal_sphere)
- `crystal_set_tool` — `{"tool": "big" | "small"}`
- `crystal_click` — `{"x": int, "y": int}`
- `crystal_proceed` — `{}`
