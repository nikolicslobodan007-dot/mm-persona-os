"""HTTP sloj Persona OS-a — Canon v1.1 §8.

Nije Django app (Canon §1 ima tačno dvanaest) nego zajednički paket, kao
`common/`. Ovde živi samo ono što je isto za svaki endpoint: oblik odgovora,
greške, header-i, idempotentnost, paginacija, audit i uloge. Poslovna pravila
ostaju u app-ovima; view-ovi ih samo pozivaju.
"""
