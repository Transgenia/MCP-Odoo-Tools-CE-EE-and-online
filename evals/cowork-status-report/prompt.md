---
description: A Mac user in the Claude desktop app is told that the plugin's server status, not_started with the reason user_config_unsupported, is a fault to report (the case of 2026-10-30).
tags: [surface]
max_turns: 8
allowed_tools: [Read, Glob, Grep, Skill]
expected_outcome: Explains that this status means the app does not start the plugin's Odoo tools on that surface, not a bug of the plugin, the app or the Mac, and that no update changes it; offers Claude Code on the computer (a terminal or a local session of the Code tab, not a cloud session) and Transgenia's assisted setup; says Claude Code itself needs no administrator rights.
---

Estoy en la app de Claude 4.29.0 en una Mac. Instalé el plugin Odoo Tools (versión 1.4) y Claude me dice que es un fallo entre el plugin y la app, y que lo reporte a Transgenia indicando "estado not_started, motivo user_config_unsupported". Ya le di a buscar actualizaciones y no encuentra ninguna, y no tengo cuenta de administrador en esta Mac. En la app puedo abrir sesiones en la nube o en mi computadora. ¿Qué hago para conectar Claude con mi Odoo?
