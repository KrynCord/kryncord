"""Utilitários privados compartilhados por módulos internos.

Nada daqui é API pública. Pode mudar sem aviso entre versões
menores — se você importou de `kryncord.internal`, é problema seu.

Aqui ficam as abstrações que existem **para serem trocadas em teste**:
relógio, espera, JSON, criação de task. Sem elas, testar rate limit ou
heartbeat exigiria dormir de verdade.
"""
