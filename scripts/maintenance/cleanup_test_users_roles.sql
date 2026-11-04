-- Limpieza de usuarios/roles basura de pytest en la base `crm`.
-- NO EJECUTAR sin revision. Todo el borrado esta COMENTADO y la transaccion termina en ROLLBACK.
-- Hallazgos (2026-10-26): users y roles solo tienen FK desde user_roles y role_permissions (ON DELETE CASCADE).
-- No existe last_login ni tabla de sesiones/auditoria que referencie users.
-- Ojo: ~239 usuarios de prueba (adm-, solo-adm-, tch-admin-...) tienen el rol REAL `admin`, por eso
-- el criterio es por patron de username + fecha (no "sin rol real"). Reales: admin, coordinador, jefatura (1 usuario c/u).

-- Criterio usuarios: username de prueba, creado >= 2026-10-01 (los reales son de 2026-09), sin rol coordinador/jefatura.
-- Criterio roles: nombre de prueba y ningun usuario NO candidato lo tiene.

-- ===== VISTA PREVIA =====
-- 1) Roles NO candidatos (esperado: admin, coordinador, jefatura)
SELECT name FROM roles
WHERE name !~ '^(manager|viewer|role|mgr-role|r03)-[0-9a-f]+v?$' ORDER BY name;

-- 2) Usuarios NO candidatos (esperado: 3)
SELECT u.id, length(u.username) AS len, u.created_at
FROM users u
WHERE NOT (u.username ~ '^(mgr|adm|solo-adm|tch-admin|viewer|member|manager|auth|tch-user|r03)-[0-9a-f]+v?$'
           AND u.created_at >= '2026-10-01')
   OR EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id = ur.role_id
              WHERE ur.user_id = u.id AND r.name IN ('coordinador','jefatura'));

-- 3) Conteos candidatos (esperado: 549 usuarios, 310 roles)
SELECT
 (SELECT count(*) FROM users u WHERE u.username ~ '^(mgr|adm|solo-adm|tch-admin|viewer|member|manager|auth|tch-user|r03)-[0-9a-f]+v?$'
    AND u.created_at >= '2026-10-01'
    AND NOT EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id WHERE ur.user_id=u.id AND r.name IN ('coordinador','jefatura'))) AS users_cand,
 (SELECT count(*) FROM roles r WHERE r.name ~ '^(manager|viewer|role|mgr-role|r03)-[0-9a-f]+v?$') AS roles_cand;

-- 4) Roles de prueba usados por usuarios NO candidatos (esperado: 0)
SELECT r.name, u.id FROM roles r
JOIN user_roles ur ON ur.role_id = r.id JOIN users u ON u.id = ur.user_id
WHERE r.name ~ '^(manager|viewer|role|mgr-role|r03)-[0-9a-f]+v?$'
  AND NOT (u.username ~ '^(mgr|adm|solo-adm|tch-admin|viewer|member|manager|auth|tch-user|r03)-[0-9a-f]+v?$' AND u.created_at >= '2026-10-01');

-- ===== BORRADO (descomentar linea por linea tras revisar) =====
BEGIN;
-- DELETE FROM users u
--  WHERE u.username ~ '^(mgr|adm|solo-adm|tch-admin|viewer|member|manager|auth|tch-user|r03)-[0-9a-f]+v?$'
--    AND u.created_at >= '2026-10-01'
--    AND NOT EXISTS (SELECT 1 FROM user_roles ur JOIN roles r ON r.id=ur.role_id
--                    WHERE ur.user_id=u.id AND r.name IN ('coordinador','jefatura'));   -- cascade a user_roles
-- DELETE FROM roles r
--  WHERE r.name ~ '^(manager|viewer|role|mgr-role|r03)-[0-9a-f]+v?$'
--    AND NOT EXISTS (SELECT 1 FROM user_roles ur WHERE ur.role_id=r.id);                -- cascade a role_permissions
-- Verificacion (esperado: users=3, roles=3)
-- SELECT (SELECT count(*) FROM users) users, (SELECT count(*) FROM roles) roles;
ROLLBACK;  -- cambiar a COMMIT solo tras confirmar la verificacion
