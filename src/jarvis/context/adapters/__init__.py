"""Infrastructure do Context Engine.

Só os providers com dado local genuíno moram aqui: **Time** e **Device**. Activity,
Calendar e Location não ganham adapter nesta fase — cada um exigiria integração
externa (agenda autenticada, serviço de localização, introspecção do sistema
operacional) que a Fase 2 proíbe, e um adapter de "valor declarado" pareceria
funcionalidade pronta sem ser. O que existe de verdade para eles é o port
`ContextProvider`, exercitado por doubles em `tests/context_doubles.py`.
"""
