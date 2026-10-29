# Casos de revision de integraciones

| Solicitud | Evidencia esperada | Regresion que detectar |
| --- | --- | --- |
| Tengo solo API key de VirtualPOS | Verificar necesidad de secret y ambiente con documentacion | Enviar la clave a varios hosts o generar firma sin secret |
| Toku devuelve 404 al listar pagos | Fallo trazado, contrato pendiente y alcance parcial explicito si se carga otro recurso | Convertir 404 en cero pagos o exito completo |
| Ultima pagina tiene items y next_cursor null | Procesar items una vez y terminar | Duplicar primera pagina o ignorar items finales |

Una consulta de prueba autorizada no habilita cambios remotos. Evita probes que creen cargos, pagos o enlaces; los diagnosticos ordinarios solo necesitan lecturas documentadas.
