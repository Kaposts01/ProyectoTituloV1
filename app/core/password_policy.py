"""Politica de claves NUEVAS o cambiadas (CRM-16A). Las claves existentes no se revalidan (ver la ficha).

Reglas: largo minimo `AUTH_PASSWORD_MIN_LENGTH` (12 por defecto), no figurar en una lista pequena de claves
comunes (comparacion sin mayusculas ni espacios), no ser una sola letra/digito repetido ni contener el usuario.
Los mensajes van en espanol y nunca incluyen la clave.
"""

from app.core.config import settings

# Lista embebida y pequena (claves filtradas mas comunes + variantes locales). Se compara en minusculas.
_COMMON_PASSWORDS = frozenset(
    """
    123456 1234567 12345678 123456789 1234567890 12345678910 123456789012 1234567891011 0123456789 987654321
    9876543210 111111 11111111 111111111111 000000 00000000 000000000000 123123 123123123 123123123123
    123321 654321 112233 121212 147258369 159753 qwerty qwerty123 qwertyuiop qwerty12345 qwertyuiop123
    asdfgh asdfghjkl zxcvbnm 1q2w3e4r 1q2w3e4r5t 1q2w3e4r5t6y 1qaz2wsx 1qaz2wsx3edc qazwsx qazwsxedc
    password password1 password12 password123 password1234 passw0rd p@ssw0rd p@ssword p@ssword123
    passwordpassword contraseña contrasena contrasena123 contraseña123 contrasenia clave clave123 clave1234
    claveclave123 micontrasena micontraseña administrador administrador1 administrador123 admin admin123
    admin1234 admin12345 administrator administrator1 root toor changeme changeme123 cambiame cambiar123
    welcome welcome1 welcome123 bienvenido bienvenido1 bienvenido123 letmein letmein123 iloveyou teamo
    teamo123 abc123 abc12345 abcd1234 abcdef abcdefgh abcdefghijkl aa123456 a1b2c3d4 monkey dragon
    football futbol futbol123 baseball master sunshine princess superman batman trustno1 starwars
    whatever shadow michael jordan23 chile chile123 chile2024 chile2025 chile2026 santiago santiago123
    colocolo colocolo123 techo techo123 techo2025 techo2026 crm crm123 crm12345 synkmetrix synkmetrix123
    usuario usuario123 invierno2025 verano2025 primavera2025 otono2025 invierno2026 verano2026
    primavera2026 otono2026 qwerty123456 password123456 contraseña123456 contrasena123456
    """.split()
)


class PasswordPolicyError(ValueError):
    """La clave nueva no cumple la politica. El mensaje es apto para el usuario."""


def validate_new_password(password: str, username: str | None = None) -> None:
    """Lanza `PasswordPolicyError` si la clave nueva no cumple la politica."""
    min_length = max(settings.auth_password_min_length, 8)
    if len(password) < min_length:
        raise PasswordPolicyError(f"La contraseña debe tener al menos {min_length} caracteres.")
    normalized = "".join(password.split()).casefold()
    if normalized in _COMMON_PASSWORDS:
        raise PasswordPolicyError("La contraseña es demasiado común. Elige otra más difícil de adivinar.")
    if len(set(normalized)) <= 2:
        raise PasswordPolicyError("La contraseña no puede repetir uno o dos caracteres. Elige otra más variada.")
    if username:
        user_norm = "".join(username.split()).casefold()
        if len(user_norm) >= 3 and user_norm in normalized:
            raise PasswordPolicyError("La contraseña no puede contener el nombre de usuario.")
