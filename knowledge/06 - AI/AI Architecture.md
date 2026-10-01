# AI Architecture

## Instrucciones globales

- [AGENTS.md](../../AGENTS.md) define prioridades de fuentes, limites arquitectonicos, seguridad, validacion y uso de memoria.

## OpenCode

- [Configuracion OpenCode](../../.opencode/opencode.json) declara Context7 como MCP remoto.
- [Skills del proyecto](../../.opencode/skills/) existentes: `prompt-optimizer`, `project-memory`, `data-modeling` y `provider-integration`.
- Las definiciones de los subagentes `obsidian-vault` y `adr-governance` mantienen el vault y revisan ADRs bajo las reglas de `AGENTS.md`.
- OpenCode es la integracion compartida de Context7 para el proyecto.

## Claude

- La configuracion especifica de Claude es local y no se versiona.
- Puede usar Context7 como herramienta complementaria, respetando `AGENTS.md` y sin redefinir reglas, arquitectura ni fuentes de verdad.
- No existen agents de Claude versionados para el proyecto.

## MCP

- Context7 aporta documentacion actualizada de tecnologias externas; nunca sustituye las fuentes de verdad de SynkmetriX.
- La configuracion compartida se mantiene en OpenCode. Cualquier configuracion local de Claude es responsabilidad del entorno que la use.

## Estado actual

La capa IA implementa reglas operativas, skills locales versionables, definiciones de los subagentes documentales `obsidian-vault` y `adr-governance`, y acceso a documentacion actualizada mediante Context7 en OpenCode. No hay otros MCP configurados.
