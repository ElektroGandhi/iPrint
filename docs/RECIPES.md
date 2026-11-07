# Recipes

Ready-made ideas. Change the entity names to your own. Entity names follow your Home Assistant language, here English.

> These recipes are examples and have not all been run on a real system. If one needs fixing, please open an issue.

## Print the shopping list at the press of a button

```yaml
alias: Print shopping list
triggers:
  - trigger: state
    entity_id: input_button.print_shopping_list
actions:
  - action: todo.get_items
    target:
      entity_id: todo.shopping_list
    data:
      status: needs_action
    response_variable: list
  - action: notify.send_message
    target:
      entity_id: notify.phomemo_t02_print
    data:
      title: Shopping
      message: >-
        {% for item in list['todo.shopping_list']['items'] %}☐ {{ item.summary }}
        {% endfor %}
```

## A morning summary

```yaml
alias: Morning summary
triggers:
  - trigger: time
    at: "07:00:00"
actions:
  - action: notify.send_message
    target:
      entity_id: notify.phomemo_t02_print
    data:
      title: Good morning!
      message: >-
        {{ now().strftime('%A, %d %B') }}
        {{ states('sensor.outdoor_temperature') }} °C, {{ states('weather.home') }}
```

## An alarm that does not depend on your phone

```yaml
alias: Water alarm on paper
triggers:
  - trigger: state
    entity_id: binary_sensor.cellar_leak
    to: "on"
actions:
  - action: iprint.print_text
    data:
      title: ⚠ WATER
      text: "Leak sensor, cellar\n{{ now().strftime('%H:%M') }}"
      size: 36
      density: darkest
```

## Print a camera picture

Pictures in `/config/www` are allowed by default.

```yaml
alias: Who rang the bell
triggers:
  - trigger: state
    entity_id: binary_sensor.doorbell
    to: "on"
actions:
  - action: camera.snapshot
    target:
      entity_id: camera.front_door
    data:
      filename: /config/www/doorbell.jpg
  - action: iprint.print_image
    data:
      path: /config/www/doorbell.jpg
```

## Warn when the paper runs out

```yaml
alias: Printer out of paper
triggers:
  - trigger: state
    entity_id: binary_sensor.phomemo_t02_paper_out
    to: "on"
actions:
  - action: notify.notify
    data:
      message: The printer is out of paper.
```

## When a job fails

A printer that is away is not a failure: the job waits in the queue and the action succeeds. An error means the job is
lost, for example because the queue is full, and the automation stops at that step. To carry on regardless, add
`continue_on_error: true` to the print action.
