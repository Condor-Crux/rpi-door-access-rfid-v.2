# Manual del Operador — Sistema de Acceso RFID
## Parador Km1151, Uspallata — Full YPF (Duchas)

---

## 1. Bienvenido / Introducción

Este sistema controla el acceso a las duchas del Full de YPF Parador Km1151. Permite asignar tarjetas RFID (fichas/llaves) a camioneros para que puedan ingresar a la ducha sin necesidad de que el personal esté presente en la puerta.

**¿Cómo funciona?**

1. El camionero solicita acceso al personal.
2. El personal crea al cliente en el sistema y le asigna una tarjeta RFID con créditos.
3. El cliente lleva la tarjeta a la puerta de la ducha y la pasa cerca del lector.
4. El sistema verifica la tarjeta: si todo está bien, la puerta se abre automáticamente por 5 segundos.
5. Cada uso consume un crédito. Cuando no quedan créditos, la tarjeta queda sin acceso.

**¿Dónde se accede al panel?**

Desde cualquier computadora o celular conectado a la red local:

```
http://[IP-del-RPi]:8000
```

*(La IP exacta la provee el administrador del sistema.)*

---

## 2. Conceptos Básicos

| Término | Significado |
|---|---|
| **Empresa** | Grupo o compañía que tiene varios clientes. "Particulares" es la empresa predeterminada para clientes individuales. |
| **Cliente / Usuario** | La persona que usa las duchas. Siempre pertenece a una empresa. |
| **Tarjeta / Llave / Ficha** | El token físico RFID que el cliente usa en la puerta. Tiene un número único (ID de tarjeta). |
| **Tipo de llave** | Define **cómo se obtienen los créditos** de la tarjeta. Ver la tabla de abajo. |
| **Crédito** | Una unidad de acceso. Cada vez que se abre la puerta se descuenta 1 crédito. Por defecto se asignan 10. |
| **Vencimiento** | Fecha y hora hasta la que la tarjeta es válida. Por defecto: 24 horas desde la asignación. Después de esa hora, la tarjeta es rechazada aunque tenga créditos. |
| **Registro de accesos** | Historial permanente de todas las pasadas de tarjeta, aprobadas o rechazadas. No se puede borrar. |
| **Blanquear** | Desvincular un conjunto de tarjetas de sus clientes para que puedan reutilizarse. Acción irreversible. |

### Tipos de llave

Cada tarjeta tiene un **tipo de llave** que distingue cómo se le asignan los créditos:

| Tipo de llave | Cómo se obtienen los créditos | Campo extra |
|---|---|---|
| **Particulares** | Se les **venden** créditos: el cliente paga y se le cargan. | — |
| **Cuenta corriente** | Se les **regalan** créditos (la empresa los cubre por cuenta corriente). | — |
| **Ticket de carga** | Se les **regalan** créditos **contra un ticket de carga** que se registra en el sistema. | **N° de ticket de carga** (número del comprobante asociado). |

> El **N° de ticket de carga** solo aplica al tipo *Ticket de carga* y queda guardado en la tarjeta como referencia del comprobante que justificó los créditos regalados.

---

## 3. Señales del Hardware (Puerta)

En la puerta de la ducha hay un lector RFID con luces LED y un buzzer (zumbador sonoro).

### Tabla de señales

| LED | Sonido | Significado |
|---|---|---|
| Verde encendido | 1 beep corto | Acceso concedido. La puerta se abre por 5 segundos. |
| Rojo encendido | 1 beep largo | Acceso denegado: tarjeta inactiva, vencida, o no registrada en el sistema. |
| Rojo encendido | 3 beeps cortos | Acceso denegado: la tarjeta no tiene créditos disponibles. |
| Sin reacción | Sin sonido | El sistema puede estar apagado o desconectado de la red. |

### ¿Cuánto tiempo se abre la puerta?

La puerta permanece abierta **5 segundos** cada vez que se concede el acceso.

---

## 4. Acceso al Panel de Administración

### Iniciar sesión

1. Abrí el navegador y entrá a `http://[IP-del-RPi]:8000`
2. Se muestra la pantalla de inicio de sesión.
3. Ingresá la **contraseña de administrador** (te la da quien administra el sistema).
4. Hacé clic en **"Ingresar"**.

> La pantalla de login **no pide nombre de usuario**, solo la contraseña.

### Duración de la sesión

La sesión dura **60 minutos** desde el último ingreso. Si el panel queda inactivo y la sesión expira, el sistema te redirige automáticamente a la pantalla de login.

---

## 5. Panel Principal (Dashboard)

Una vez que iniciás sesión, entrás al **Panel Principal**.

### Panel izquierdo — Lista de cuentas

Muestra todas las tarjetas registradas en el sistema con la siguiente información por fila:

| Columna | Descripción |
|---|---|
| **ID de tarjeta** | Número único de la tarjeta RFID. |
| **Cliente** | A quién está asignada. |
| **Estado** | Activa o Inactiva. |
| **Vencimiento** | Fecha y hora hasta la que es válida. |
| **Créditos** | Cuántos accesos le quedan. |
| **Recargar** | Botón para agregar créditos rápidamente. |

### Panel derecho — Eventos en tiempo real

Muestra los **últimos ~20 accesos** registrados, actualizados en tiempo real:

- Fondo **verde**: acceso concedido.
- Fondo **rojo**: acceso denegado (incluye el motivo).
- Cada evento muestra: ID de tarjeta, resultado, motivo (si fue denegado), y hora.

### Indicador de conexión

Un **punto verde** en la esquina indica que el panel está conectado y recibiendo datos en tiempo real. Si el punto está gris o desaparece, recargá la página.

---

## 6. Gestión de Empresas

Las empresas agrupan a los clientes. "Particulares" siempre existe y es para clientes individuales.

### Crear una nueva empresa

1. En el panel, buscá la opción **"Empresas"** o **"Nueva empresa"**.
2. Completá el nombre de la empresa.
3. Guardá.

La empresa queda disponible para asignarle clientes.

> Si solo atendés clientes individuales (camioneros sueltos), no necesitás crear empresas adicionales. Usá siempre "Particulares".

---

## 7. Gestión de Clientes

### Crear un nuevo cliente

1. Hacé clic en **"Nuevo cliente"** o **"Agregar cliente"**.
2. Completá los campos:
   - **Nombre** (obligatorio)
   - **Apellido** (obligatorio)
   - **Email** (opcional)
   - **Empresa** (seleccioná de la lista; para clientes sueltos elegí "Particulares")
3. Hacé clic en **"Guardar"**.

El cliente queda registrado pero **sin tarjeta asignada todavía**. El siguiente paso es agregar la tarjeta.

### Ver clientes registrados

Los clientes aparecen en la lista del panel principal asociados a sus tarjetas. También podés acceder al listado completo desde el menú.

---

## 8. Gestión de Tarjetas (Fichas / Llaves)

### Agregar una tarjeta a un cliente

1. Seleccioná el cliente de la lista.
2. Hacé clic en **"Agregar tarjeta"**.
3. Ingresá el ID de la tarjeta — hay dos formas:

#### Opción A: Lector USB (recomendado)

1. Conectá el lector USB RFID a la computadora donde estás trabajando.
2. Hacé clic dentro del campo **"ID de tarjeta"** para que el cursor quede ahí.
3. Acercá la tarjeta física al lector.
4. El número se completa automáticamente en el campo.

> **Importante:** El cursor debe estar dentro del campo ID de tarjeta antes de pasar la tarjeta. Si el cursor está en otro campo o en otro programa, el número se escribirá donde no corresponde.

#### Opción B: Ingreso manual

1. Escribí el número de ID directamente en el campo **"ID de tarjeta"**.
2. Revisá que no haya errores de tipeo.

#### Configurar créditos y vencimiento

- **Créditos:** Por defecto son **10**. Podés cambiarlo según lo que haya pagado el cliente.
- **Vencimiento:** Por defecto son **24 horas** desde el momento actual. Podés ajustarlo si necesitás.

4. Hacé clic en **"Guardar"** (o "Agregar").
5. La tarjeta queda activa de inmediato.
6. Entregá la tarjeta al camionero.

---

### Editar una tarjeta existente

1. Encontrá la tarjeta en la lista del panel principal (o en el perfil del cliente).
2. Hacé clic en el ícono de edición (lápiz o "Editar").
3. Podés modificar:
   - **Estado:** Activa / Inactiva (desactivar impide el acceso sin borrar la tarjeta).
   - **Créditos:** Cambiá la cantidad.
   - **Vencimiento:** Extendé o acortá la fecha/hora.
4. Guardá los cambios.

---

### Eliminar una tarjeta

1. Encontrá la tarjeta.
2. Hacé clic en **"Eliminar"** (o ícono de papelera).
3. Confirmá la acción.

> La tarjeta queda desvinculada del cliente y puede asignarse a otro cliente en el futuro.

---

### Recargar créditos (desde el panel principal)

1. En la lista del panel, encontrá la fila de la tarjeta.
2. Hacé clic en el botón **"Recargar"**.
3. Ingresá la cantidad de créditos a agregar.
4. Confirmá. Los créditos se actualizan en el momento.

---

## 9. Clientes Particulares (Sin Empresa)

Los camioneros que vienen solos (sin pertenecer a ninguna empresa) se registran como **Particulares**.

### Flujo completo para un cliente particular

1. En la lista de empresas, seleccioná **"Particulares"** (siempre aparece primera en la lista).
2. Hacé clic en **"Nuevo cliente"**.
3. Completá nombre completo (obligatorio). Email es opcional.
4. Guardá el cliente.
5. Cobrá el servicio al cliente (esto se hace fuera del sistema — efectivo, transferencia, etc.).
6. Agregá la tarjeta al cliente (seguí el flujo del punto 8: "Agregar tarjeta a un cliente").
7. Entregá la tarjeta. Por defecto vence en **24 horas**, tené eso en cuenta.

> Si el cliente quiere más tiempo o más accesos, ajustá los créditos y el vencimiento antes de guardar.

---

## 10. Recuperar Tarjetas Abandonadas

Los clientes de "Particulares" frecuentemente **dejan la tarjeta** en un recipiente a la salida de las duchas. Estas tarjetas deben recuperarse periódicamente para poder reutilizarlas con nuevos clientes.

### Proceso de recuperación ("Blanquear")

1. Juntá las tarjetas abandonadas del recipiente.
2. En el panel, andá a la pestaña **"Recuperar tarjeta/llave"**.
3. Conectá el lector USB a la computadora.
4. Pasá cada tarjeta por el lector una a una. Cada ID se va agregando a una lista en pantalla.
   - También podés ingresar los IDs manualmente si no tenés el lector disponible.
5. Revisá la lista en pantalla y verificá que estén todas las tarjetas que querés liberar.
6. Cuando la lista esté completa, hacé clic en **"Blanquear"**.

---

> ⚠️ **ADVERTENCIA: El blanqueo es IRREVERSIBLE.**
>
> Al hacer clic en "Blanquear", todas las tarjetas de la lista quedan desvinculadas de sus clientes anteriores. No se puede deshacer. Si una tarjeta estaba asignada a un cliente que todavía la está usando, **perderá el acceso inmediatamente**.
>
> **Revisá bien la lista antes de confirmar.**

---

Después del blanqueo, esas tarjetas quedan libres y listas para asignarse a nuevos clientes.

---

## 11. Registro de Accesos

### ¿Qué es?

Cada vez que alguien pasa una tarjeta por el lector de la puerta — sea que se abra o no — el sistema guarda un **registro permanente**. Este registro no se puede borrar y sirve como auditoría.

### ¿Dónde se ve?

- **En tiempo real:** En el panel derecho del Dashboard (últimos ~20 eventos).
- **En el historial completo:** Disponible desde el menú de accesos/registros.

### ¿Qué información muestra cada evento?

| Campo | Descripción |
|---|---|
| **ID de tarjeta** | Número de la tarjeta que se pasó. |
| **Resultado** | "Concedido" o "Denegado". |
| **Motivo** | Si fue denegado: tarjeta inactiva, vencida, no encontrada, o sin créditos. |
| **Hora** | Fecha y hora del evento (en UTC). |

> Las horas se muestran en **UTC (hora universal)**. Uspallata está en UTC-3, así que restá 3 horas para la hora local en verano (o 3 horas en invierno — Argentina no cambia el horario).

---

## 12. Resolución de Problemas

### El panel no carga / no abre la página

| Posible causa | Qué hacer |
|---|---|
| La Raspberry Pi está apagada | Verificá que esté encendida y conectada. |
| La PC no está en la red local | Verificá que tenés WiFi o cable de la misma red que la RPi. |
| IP incorrecta | Confirmá la IP del sistema con el administrador. |

---

### El indicador de conexión (punto) está gris o apagado

La conexión en tiempo real se cortó. **Recargá la página** (F5 o botón de actualizar). Si no vuelve, chequeá que la RPi esté encendida.

---

### Se pasó la tarjeta en la puerta pero no pasó nada (ni LED ni sonido)

1. Verificá en el panel que la tarjeta esté registrada en el sistema.
2. Verificá que la tarjeta tenga **créditos disponibles**.
3. Verificá que la tarjeta **no esté vencida**.
4. Si todo parece bien, el sistema puede estar offline — revisá si el panel abre.

---

### La tarjeta fue rechazada (LED rojo)

Mirá el registro de accesos en el panel para ver el motivo exacto:

| Motivo | Solución |
|---|---|
| **Sin créditos** (3 beeps) | Recargar créditos desde el panel. |
| **Vencida** | Editar la tarjeta y ampliar la fecha de vencimiento. |
| **Inactiva** | Editar la tarjeta y activarla. |
| **No encontrada** | La tarjeta no está en el sistema. Agregarla al cliente correspondiente. |

---

### El ID de la tarjeta no se completa cuando uso el lector USB

- Verificá que el lector esté conectado correctamente al puerto USB.
- Asegurate de que el cursor esté dentro del campo **"ID de tarjeta"** antes de pasar la ficha.
- Si el cursor estaba en otro lugar, el número puede haberse escrito en otro campo o aplicación. Borrá y volvé a intentarlo con el cursor en el lugar correcto.

---

### La puerta se abrió cuando no debería

1. Revisá el **registro de accesos** de inmediato para identificar qué tarjeta fue usada.
2. Verificá si fue un acceso autorizado o no.
3. Si fue un acceso no autorizado, **desactivá la tarjeta** desde el panel (editarla y cambiar estado a "Inactiva").
4. Notificá al administrador del sistema.

---

### La sesión venció y me mandó al login

Es normal. La sesión dura 60 minutos. Ingresá la contraseña nuevamente para continuar.

---

## 13. Glosario

| Término | Definición |
|---|---|
| **Blanquear** | Proceso que desvincula un conjunto de tarjetas de sus clientes. Las tarjetas quedan libres para reutilizar. Es irreversible. |
| **Buzzer** | Dispositivo sonoro en la puerta que emite beeps para indicar el resultado de la pasada. |
| **Crédito** | Unidad de acceso. 1 crédito = 1 entrada a la ducha. |
| **Dashboard** | Panel principal del sistema, donde se ve la lista de tarjetas y los eventos en tiempo real. |
| **Empresa** | Agrupación de clientes. "Particulares" es la predeterminada. |
| **Ficha / Llave / Tarjeta** | El token físico RFID que el cliente usa en la puerta. |
| **ID de tarjeta** | Número único grabado en cada tarjeta RFID. Identifica de forma exclusiva a la tarjeta. |
| **Inactiva** | Estado de una tarjeta que fue desactivada. No permite acceso aunque tenga créditos y no esté vencida. |
| **Lector RFID** | Dispositivo que lee las tarjetas. Hay uno en la puerta (conectado a la RPi) y puede haber uno USB en el mostrador. |
| **Particulares** | Empresa especial del sistema para clientes individuales (camioneros sin empresa). |
| **Raspberry Pi (RPi)** | La pequeña computadora que controla el sistema. Está conectada a la red local y a la puerta. |
| **Registro de accesos** | Historial permanente de todas las pasadas de tarjeta. No se puede borrar. |
| **RFID** | Tecnología de identificación por radiofrecuencia. Funciona por proximidad, sin contacto. |
| **SSE / Tiempo real** | Tecnología que actualiza la pantalla automáticamente sin necesidad de recargar la página. |
| **UTC** | Hora universal. Argentina está en UTC-3 (se le restan 3 horas para obtener la hora local). |
| **Vencimiento** | Fecha y hora hasta la que una tarjeta puede usarse. Por defecto son 24 horas desde la asignación. |

---

*Sistema desarrollado para Parador Km1151 — Uspallata, Mendoza.*
*Panel disponible en: `http://[IP-del-RPi]:8000` — Ayuda en: `http://[IP-del-RPi]:8000/help`*
