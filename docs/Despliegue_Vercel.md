# Aula EDA en Vercel

La versión online conserva el mismo motor Python de `eda/application.py`, `eda/broker.py` y `eda/consumers.py`. `api/lab.py` adapta la ejecución a una Vercel Function y `eda/cloud.py` permite continuar la práctica entre invocaciones.

## Sesiones de los alumnos

Cada navegador guarda su propia sesión JSON en `localStorage`. Una petición envía esa sesión y la acción solicitada al backend. Python restaura los registros en SQLite en memoria, ejecuta una acción con los mismos consumidores y devuelve el resultado y la nueva sesión. El navegador guarda el progreso actualizado.

No se utiliza un archivo SQLite temporal como almacenamiento permanente en Vercel. La versión local conserva su base de datos en `data/aula.sqlite3`; la versión online conserva el progreso en el navegador. La sesión incluye el estado de correlación de Envíos, los eventos, las entregas pendientes, los intentos y la cola de fallos.

Recargar la página conserva la práctica en ese navegador. Abrir el enlace desde otro dispositivo o navegador comienza una práctica independiente. El modo automático online avanza mientras la pestaña está visible y abierta; no hay un trabajador permanente en segundo plano. Borrar los datos del sitio elimina esa sesión. El botón Reiniciar solo borra la práctica del navegador actual.

Este almacenamiento es adecuado para ejercicios con datos ficticios. No constituye una base de datos comercial centralizada ni una fuente de auditoría confiable: la sesión está bajo control del alumno. Para un sistema compartido real se necesitarían una base de datos externa, autenticación y consumidores durables.

## Archivos del despliegue

| Archivo | Función |
| --- | --- |
| `vercel.json` | Build estático y configuración de la función Python |
| `scripts/build_vercel.py` | Copia la interfaz a `public` y activa el modo online |
| `api/lab.py` | API HTTP de Vercel |
| `eda/cloud.py` | Restaura y exporta la sesión sin ejecutar SQL del cliente |
| `web/runtime.js` | Transporte local/online y persistencia del navegador |
| `web/runtime.json` | Configuración local; el build genera la variante online |
| `tests/test_cloud.py` | Pruebas del flujo entre invocaciones y aislamiento de alumnos |

## Repetir las comprobaciones

```bash
python -m unittest discover -s tests -v
python scripts/build_vercel.py
```

Se verifican 19 casos del motor local y del adaptador online. En la página publicada, crea un pedido, procesa una entrega, paga cuando esté reservado y completa las entregas. Recarga para comprobar la persistencia. Abre otra sesión de navegador para comprobar que no comparten inventario.

La sesión se limita a 1 MB, 1000 registros por tabla y 5000 registros en total. Si alcanza un límite, la acción no sobrescribe el progreso anterior; reinicia el laboratorio para comenzar otra práctica.

## Publicar desde GitHub

Importa `jc2709/eventos` en Vercel con la raíz del repositorio. `vercel.json` define el build `python3 scripts/build_vercel.py` y la salida `public`; el archivo de función se detecta en `api/lab.py`. No se necesitan claves de API, variables secretas ni una base de datos externa.

Documentación oficial consultada: [Python Functions in the api directory](https://vercel.com/docs/functions/runtimes/python/api-directory) y [Configuración de vercel.json](https://vercel.com/docs/project-configuration/vercel-json).
