"""Erros do Skill Framework.

`SkillError` é falha de **domínio**: ou a entrada viola uma regra de negócio da
própria Skill, ou a Skill não conseguiu cumprir o que se propôs. Falha de
infraestrutura chega como `ToolError` vindo do router e não é traduzida aqui —
achatar as duas famílias esconderia a diferença entre "o pedido está errado" e
"o mundo lá fora falhou", que é exatamente o que o Agent Runtime precisa saber
para decidir o que dizer ao usuário.

Como em todo o resto do projeto: nenhuma mensagem carrega parâmetro, conteúdo de
arquivo ou resultado de tool.
"""

from jarvis.errors import DomainError


class SkillError(DomainError):
    """Raiz das falhas declaradas por uma Skill."""


class SkillRegistryError(SkillError):
    """Registro inválido: nome duplicado, descritor malformado, handler ausente."""


class UnknownSkillError(SkillError):
    """Nenhuma Skill com esse nome está registrada.

    É o que acontece quando o modelo inventa um nome de capacidade
    (`PHASE-5.md §26`). O executor traduz para uma negação auditada, não para um
    crash: um nome alucinado é um caso previsto, não um bug.
    """


class SkillInputError(SkillError):
    """Os parâmetros violam uma regra de negócio da Skill.

    Distinta de `ToolInvalidInputError`: aquela é o schema técnico; esta é a
    regra que só a Skill conhece (ex. "o caminho precisa ser relativo").
    """


class SkillExecutionError(SkillError):
    """A Skill executou e não conseguiu concluir.

    Usada quando a causa é da própria Skill. Falha de Tool sobe como `ToolError`
    e é classificada pelo executor.
    """
