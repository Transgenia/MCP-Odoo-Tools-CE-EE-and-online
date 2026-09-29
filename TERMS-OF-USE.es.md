> **Nota (no forma parte del texto legal):** borrador para revisión por un abogado; no constituye
> asesoría legal. Contiene el mismo texto que `Terminos-de-uso-odoo-tools-v2.0-2026-09.docx`.

# TÉRMINOS DE USO

**DE ODOO-TOOLS (EDICIÓN GRATUITA) DE CENTRUM TRANSGENIA SAS (TRANSGENIA.ORG)**

**Versión 2.0 – Fecha de emisión: septiembre de 2026**

Los presentes Términos de Uso (en adelante, los **“Términos”**) establecen las condiciones bajo las cuales Centrum Transgenia SAS (en adelante, **“Transgenia.org”** o **“Transgenia”**) pone a disposición de cualquier persona física o moral que lo descargue, instale o utilice (en adelante, **“el Usuario”**) la edición gratuita de odoo-tools y los servicios asociados que se describen más adelante. El Software se distribuye bajo la **Licencia MIT**. Estos Términos complementan dicha licencia y en ningún caso la restringen: regulan la relación del Usuario con Transgenia.org en materia de marcas, soporte, privacidad y tratamiento de datos, licencias de terceros, uso de los canales y repositorios de Transgenia.org, y ley aplicable.

---

## 1. OBJETO Y ALCANCE

### 1.1 El Software

- Por **“el Software”** se entiende la edición gratuita de odoo-tools publicada por Transgenia.org en el repositorio público de GitHub Transgenia/MCP-Odoo-Tools-CE-EE-and-online, que comprende:
  - (a) el *plugin* odoo-tools para Claude Code;
  - (b) el servidor MCP `odoo-mcp-tools`, publicado también en PyPI;
  - (c) la interfaz de línea de comandos (CLI) de respaldo;
  - (d) las herramientas para crear un entorno local de pruebas (*sandbox*) con Odoo Community Edition, versiones 10.0 a 19.0 (las imágenes de Odoo y de PostgreSQL que esas herramientas descargan se rigen por la sección 4.1);
  - (e) la imagen de contenedor `ghcr.io/transgenia/odoo-mcp-tools` (los componentes de terceros incluidos en la imagen, como el sistema operativo base y el intérprete de Python, conservan sus propias licencias); y
  - (f) su documentación, habilidades (*skills*), comandos, agentes y *hooks*.
- Por **“los Servicios”** se entienden el repositorio público y su sistema de *issues*, la documentación publicada por Transgenia.org, los canales oficiales de contacto descritos en la sección 14 y cualquier soporte gratuito que Transgenia.org preste en relación con el Software.

### 1.2 Carácter gratuito y otras ediciones

- El Software y los Servicios descritos en estos Términos se ofrecen sin costo.
- La edición premium (odoo-tools premium, que incluye el servidor de lenguaje `odoo-tools-lsp`) es un producto distinto, de código cerrado, que se rige por su propio Acuerdo de Licencia para Usuario Final (EULA) y por el **Contrato Comercial Macro** que el cliente celebre con Transgenia.org. Estos Términos no otorgan derecho alguno sobre la edición premium. El acceso a la edición premium se concede únicamente a solicitud dirigida a Transgenia.org por correo electrónico o por WhatsApp (sección 14), conforme a su EULA.

### 1.3 Lo que no incluye

- Transgenia.org no proporciona instancias, licencias ni suscripciones de Odoo Enterprise Edition ni de Odoo Online, que son productos de Odoo S.A. El entorno local de pruebas incluye únicamente Odoo Community Edition. Para usar el Software con Odoo Enterprise Edition u Odoo Online, el Usuario debe conectar su propia instancia, debidamente licenciada.
- Transgenia.org no aloja, opera ni respalda la instancia de Odoo del Usuario ni sus datos.

---

## 2. RELACIÓN CON LA LICENCIA MIT

### 2.1 Licencia del Software

- El Software se licencia bajo la Licencia MIT, cuyo texto se incluye en el archivo `LICENSE` del repositorio. Esa licencia permite a cualquier persona usar, copiar, modificar, fusionar, publicar, distribuir, sublicenciar y vender copias del Software, con la condición de incluir el aviso de derechos de autor y el aviso de permiso en todas las copias o partes sustanciales del Software.

### 2.2 Prevalencia de la Licencia MIT

- En todo lo relativo al Software, **la Licencia MIT prevalece sobre cualquier disposición de estos Términos**. Ninguna disposición de estos Términos limita, condiciona, suspende ni revoca los derechos que la Licencia MIT otorga, ni añade condiciones para ejercerlos.
- Si alguna disposición de estos Términos pudiera interpretarse como una restricción al uso, copia, modificación o distribución del Software, esa disposición se entenderá referida exclusivamente a los Servicios y a la relación del Usuario con Transgenia.org.

### 2.3 Materias que regulan estos Términos

- Estos Términos regulan exclusivamente: el uso de las marcas de Transgenia.org; el soporte y los Servicios; la privacidad y el tratamiento de datos; la relación con licencias y servicios de terceros; el uso aceptable de los Servicios; y la ley aplicable y la jurisdicción.

---

## 3. PROPIEDAD INTELECTUAL Y MARCAS

### 3.1 Derechos de autor

- Los derechos de autor sobre el Software corresponden a Transgenia.org y, en lo que respecta a sus aportaciones, a los terceros autores identificados en el archivo `NOTICE` del repositorio (entre ellos, los componentes reutilizados del proyecto odoo-agent, publicado bajo la Licencia MIT) y a los demás contribuidores, conforme al historial del repositorio.
- La Licencia MIT es una licencia no exclusiva y no implica cesión ni transmisión de los derechos patrimoniales de autor.

### 3.2 Marcas de Transgenia.org

- Los nombres “Transgenia” y “Transgenia.org”, sus logotipos y demás signos distintivos pertenecen a Transgenia.org y se protegen conforme a la Ley Federal de Protección a la Propiedad Industrial (LFPPI). La Licencia MIT no otorga derechos sobre ellos.
- Quien modifique o redistribuya el Software debe conservar el aviso de derechos de autor que exige la Licencia MIT y puede indicar con veracidad que su versión deriva de odoo-tools de Transgenia.org. Sin autorización previa y por escrito de Transgenia.org, no podrá usar esas marcas de modo que sugiera que su versión es la oficial, que Transgenia.org la respalda o que Transgenia.org presta soporte sobre ella.

### 3.3 Marcas de terceros

- “Odoo” es una marca de Odoo S.A. El Software es una herramienta independiente, sin afiliación con Odoo S.A. y sin su respaldo, y menciona esa marca sólo para identificar la plataforma con la que es compatible.
- “Claude” y “Claude Code” son marcas de Anthropic, PBC. Las demás marcas citadas (GitHub, PyPI y Docker, entre otras) pertenecen a sus respectivos titulares.

### 3.4 Contribuciones

- Las contribuciones que el Usuario envíe al repositorio público (*pull requests*, parches o documentación) se aceptan bajo la Licencia MIT, conforme al archivo `CONTRIBUTING.md`. Al enviarlas, el Usuario declara que tiene derecho a aportarlas bajo esa licencia y que no contienen código tomado de proyectos con licencias incompatibles, en particular de proyectos con licencia AGPL.

---

## 4. LICENCIAS Y SERVICIOS DE TERCEROS

### 4.1 Odoo Community Edition

- Odoo Community Edition se distribuye bajo la GNU Lesser General Public License, versión 3 (LGPL-3). El entorno local de pruebas descarga imágenes de contenedor de Odoo Community Edition y de PostgreSQL (réplicas de las imágenes oficiales, publicadas en `ghcr.io/transgenia`, con respaldo en Docker Hub), que se rigen por sus propias licencias: LGPL-3 y PostgreSQL License, respectivamente.

### 4.2 Odoo Enterprise Edition

- Odoo Enterprise Edition se licencia por Odoo S.A. bajo la Odoo Enterprise Edition License v1.0 y requiere una suscripción vigente con Odoo S.A. o con uno de sus socios autorizados. Contar con esa licencia y cumplirla es responsabilidad exclusiva del Usuario.

### 4.3 Odoo Online

- Odoo Online es el servicio en la nube (SaaS) de Odoo S.A. y se rige por los términos de servicio y de suscripción que el Usuario haya aceptado con Odoo S.A. Para usar el Software con Odoo Online, el plan contratado debe incluir acceso a la API externa. Verificar ese acceso y cumplir dichos términos es responsabilidad del Usuario.

### 4.4 Otros componentes

- El Software incluye o puede utilizar otros componentes con licencias propias, en particular las dependencias de npm que instala la CLI de respaldo, las dependencias de Python del servidor MCP y los paquetes opcionales de Python que el Usuario decida instalar. Esas licencias se indican en los metadatos y la documentación de cada componente; el archivo `NOTICE` identifica el código de terceros incorporado al repositorio. Nada en estos Términos limita los derechos que esas licencias otorgan.

### 4.5 Cliente MCP y proveedor del modelo de IA

- El Software se ejecuta dentro del cliente MCP que elija el Usuario (por ejemplo, Claude Code). Los resultados de las herramientas se devuelven a ese cliente y, a través de él, al proveedor del modelo de IA del Usuario (por ejemplo, Anthropic). Ese tratamiento se rige por los términos que el Usuario tenga con dichos proveedores; Transgenia.org no es parte de esos acuerdos.

### 4.6 Compatibilidad

- Transgenia.org no garantiza que el Software siga siendo compatible con versiones futuras de Odoo ni con los cambios o retiros de interfaces que anuncie Odoo S.A., como los *endpoints* XML-RPC y JSON-RPC.

---

## 5. PRIVACIDAD, CREDENCIALES Y TELEMETRÍA

### 5.1 Ejecución local

- El Software se ejecuta en el equipo del Usuario o en la infraestructura que el Usuario controla. Transgenia.org no opera ningún servidor para el Software y no recibe, intermedia ni conserva datos provenientes de él: ni credenciales, ni registros de Odoo, ni instrucciones (*prompts*).
- La descarga del Software y de las imágenes de contenedor desde GitHub, PyPI, ghcr.io o Docker Hub se rige por los términos y las políticas de privacidad de esas plataformas.

### 5.2 Credenciales

- Las credenciales de Odoo (URL, base de datos, usuario y clave de API o contraseña) se capturan como opciones del *plugin* en Claude Code. La clave de API y la contraseña se guardan como opciones sensibles en el almacén de credenciales de Claude Code: el llavero del sistema operativo cuando está disponible (por ejemplo, el Llavero de macOS) o, en otro caso, un archivo local de credenciales con acceso restringido a la cuenta del Usuario.
- Las credenciales se envían únicamente a la instancia de Odoo que el Usuario configura. **Transgenia.org nunca las recibe.**
- Algunas funciones opcionales guardan credenciales o contraseñas en archivos locales de configuración (`.env`) que se crean en el equipo del Usuario con permisos restringidos a su propietario: la CLI de respaldo, el entorno local de pruebas y el modo de contenedor. Proteger esos archivos y eliminarlos cuando dejen de usarse corresponde al Usuario.
- Si el Usuario despliega el servidor MCP en modo HTTP, las credenciales viajan en los encabezados de cada solicitud hacia el servidor que el propio Usuario opera. Protegerlo (por ejemplo, con TLS y control de acceso) es responsabilidad del Usuario.
- Transgenia.org nunca solicitará la contraseña ni la clave de API de Odoo del Usuario por chat, correo electrónico, WhatsApp u otro canal. Cuando un servicio contratado requiera acceso a la instancia de Odoo del Usuario, se hará mediante un usuario dedicado, creado y revocable por el Usuario, conforme al Contrato Comercial Macro.

### 5.3 Datos consultados en Odoo

- Cuando el Usuario o su agente de IA lo solicitan, el Software lee y, si el Usuario lo permite, modifica registros de su instancia de Odoo, que pueden contener datos personales. El Software no conserva copia propia de esos datos: los devuelve al cliente MCP, que los envía al proveedor del modelo conforme a la sección 4.5.
- Respecto de esos datos, el Usuario (o la organización a la que representa) actúa como responsable del tratamiento. Transgenia.org no accede a ellos. Se recomienda usar un usuario de Odoo con privilegios mínimos y activar el modo de solo lectura para tareas de exploración.

### 5.4 Telemetría opcional (opt-in)

- La telemetría está **desactivada por defecto**. Solo se habilita si el Usuario la activa expresamente (`ODOO_TELEMETRY=opt-in`).
- Aun activada, el Software no envía nada por sí mismo: genera en pantalla un informe sin datos personales que el Usuario revisa y, si así lo decide, comparte manualmente. El informe se limita a datos técnicos agregados: versión del *plugin*, versión y edición de Odoo, tipo de despliegue, transporte y contadores de uso por herramienta.
- El informe nunca incluye URL, nombre de la base de datos, usuario, correo electrónico, secretos, nombres de empresas o clientes, contenido de registros, rutas de archivos ni nombres de equipo.
- Los *endpoints* opcionales de observabilidad (OpenTelemetry y Prometheus) envían datos únicamente a los colectores que el propio Usuario configura, nunca a Transgenia.org.

### 5.5 Datos que Transgenia.org sí recibe

- Transgenia.org solo recibe los datos que el Usuario le proporciona voluntariamente al contactarla por sus canales oficiales, al abrir un *issue* o al contratar servicios. Esos datos se tratan conforme al Aviso de Privacidad de Transgenia.org, disponible en <https://transgenia.org/legal-privacidad.html> (versión en inglés: <https://transgenia.org/en/legal-privacy.html>).
- Los *issues* del repositorio público son visibles para cualquier persona. El Usuario no debe publicar en ellos credenciales, datos personales ni información confidencial de su instancia de Odoo.

---

## 6. PROTECCIÓN DE DATOS PERSONALES

### 6.1 Usuarios en la Unión Europea (cumplimiento del RGPD)

- Cuando el Usuario se ubique en la Unión Europea o trate datos de personas que se encuentren en ella, cada parte cumplirá, en lo que le resulte aplicable, el Reglamento (UE) 2016/679, Reglamento General de Protección de Datos (RGPD/GDPR).
- Dado que Transgenia.org no accede a los datos que el Usuario trata con el Software, no actúa como encargado del tratamiento respecto de ellos. Si el Usuario contrata servicios en los que Transgenia.org sí acceda a datos personales por cuenta del Usuario, las partes formalizarán el acuerdo de encargo del tratamiento (*Data Processing Agreement*, DPA) que corresponda conforme al artículo 28 del RGPD.
- Respecto de los datos que Transgenia.org recibe como responsable (sección 5.5), los titulares pueden ejercer sus derechos de acceso, rectificación, supresión, limitación del tratamiento, portabilidad y oposición por los medios indicados en la sección 6.2.

### 6.2 Usuarios en México (Ley Federal de Protección de Datos Personales en Posesión de los Particulares)

- Transgenia.org y el Usuario, en lo que corresponda a cada uno, cumplirán la Ley Federal de Protección de Datos Personales en Posesión de los Particulares (LFPDPPP), publicada en el Diario Oficial de la Federación el 20 de marzo de 2025, que abrogó la ley del mismo nombre de 2010, y la normativa que de ella derive, cuando traten datos personales de titulares en México.
- El tratamiento de los datos personales que recibe Transgenia.org se describe en su Aviso de Privacidad (<https://transgenia.org/legal-privacidad.html>), que estos Términos no reproducen y que prevalece en esa materia. Los derechos ARCO (Acceso, Rectificación, Cancelación y Oposición) se ejercen mediante solicitud dirigida a notificaciones@transgenia.org. La dirección dev@transgenia.org se reserva para asuntos técnicos.
- Si el Usuario almacena o consulta datos personales en su instancia de Odoo mediante el Software, lo hace bajo su exclusiva responsabilidad como responsable del tratamiento y debe contar con los avisos de privacidad, el consentimiento o la base legal que corresponda y las medidas de seguridad que exija la ley.

### 6.3 Solicitudes de eliminación de datos (derecho de supresión)

- Cualquier titular de datos (en México, en la Unión Europea o en cualquier otra jurisdicción) podrá solicitar la supresión de los datos personales que obren en poder de Transgenia.org, al amparo de la legislación que le sea aplicable, escribiendo a notificaciones@transgenia.org.
- Transgenia.org atenderá esas solicitudes sin dilación indebida, siempre que el solicitante acredite su identidad y su legitimación, y que no exista una obligación legal que impida la supresión.
- Las solicitudes relativas a datos almacenados en la instancia de Odoo del Usuario deben dirigirse al Usuario, en su calidad de responsable, ya que Transgenia.org no tiene acceso a ellos.

---

## 7. DERECHOS DE AUTOR: LEY FEDERAL DEL DERECHO DE AUTOR Y DMCA

### 7.1 Ley Federal del Derecho de Autor (México) e INDAUTOR

- El Software es un programa de computación y, como tal, una obra protegida por la Ley Federal del Derecho de Autor (LFDA) en los mismos términos que las obras literarias (artículos 13, fracción XI, 101 y 102).
- La LFDA distingue los derechos morales, que corresponden a las personas autoras y son inalienables e irrenunciables (artículos 19 y 21), de los derechos patrimoniales, que el titular puede licenciar (artículo 30). La Licencia MIT es una licencia de uso no exclusiva sobre los derechos patrimoniales: no los cede y no afecta los derechos morales. La titularidad se mantiene en Transgenia.org y en los terceros autores que correspondan.
- Transgenia.org podrá registrar el Software ante el Instituto Nacional del Derecho de Autor (INDAUTOR). Ese registro no altera la Licencia MIT ni los derechos que esta otorga al Usuario y a cualquier tercero. Las reclamaciones por infracción en México se atienden conforme a la LFDA.

### 7.2 Reclamaciones conforme a la ley de los Estados Unidos (DMCA)

- En la medida en que resulte aplicable, cuando alguna persona alegue que el Software, el repositorio o la documentación infringen derechos de autor conforme a la ley de los Estados Unidos, o cuando el material esté alojado en una plataforma sujeta a ella (como GitHub), se atenderá el procedimiento de la Digital Millennium Copyright Act (DMCA). Las notificaciones pueden dirigirse a notificaciones@transgenia.org o presentarse mediante el procedimiento de GitHub.
- Mientras se resuelve una reclamación, Transgenia.org podrá retirar o deshabilitar el material presuntamente infractor en sus repositorios y canales, y atenderá las contranotificaciones que se presenten conforme a la DMCA.

---

## 8. SOPORTE Y SERVICIOS PROFESIONALES

### 8.1 Soporte gratuito de mejor esfuerzo

- Transgenia.org podrá atender dudas, reportes de errores y solicitudes de funcionalidad a través de los *issues* del repositorio público, en la medida de sus posibilidades. Ese soporte no incluye niveles de servicio, tiempos de respuesta ni obligación de corregir, actualizar o mantener el Software.
- Transgenia.org podrá modificar, dejar de mantener o retirar el Software o los Servicios en cualquier momento. Las copias del Software que el Usuario ya haya obtenido conservan la Licencia MIT.

### 8.2 Servicios de pago

- El mantenimiento, el soporte con niveles de servicio, la capacitación, los desarrollos a la medida, las migraciones de Odoo, el despliegue asistido y la edición premium se contratan con Transgenia.org por sus canales oficiales y se rigen por el Contrato Comercial Macro y sus anexos, no por estos Términos.

### 8.3 Canales oficiales

- Los únicos canales oficiales de Transgenia.org para el Software son los indicados en la sección 14. Cualquier comunicación que provenga de otros medios y ofrezca soporte en nombre de Transgenia.org, o que solicite credenciales, debe considerarse no oficial.

### 8.4 Reporte de vulnerabilidades

- Las vulnerabilidades de seguridad deben reportarse de forma privada conforme al archivo `SECURITY.md` del repositorio, y no mediante *issues* públicos.

---

## 9. USO ACEPTABLE

- Las reglas de esta sección aplican a los Servicios y recuerdan obligaciones que el Usuario ya tiene por ley o por sus acuerdos con terceros; no son condiciones de la Licencia MIT (sección 2.2). En su relación con Transgenia.org y al usar los Servicios, el Usuario se compromete a no:
  - acceder, mediante el Software, a instancias de Odoo o a datos para los que no tenga autorización;
  - usar el Software para eludir la licencia de Odoo Enterprise Edition o los términos de Odoo Online;
  - tratar datos personales en contravención de la legislación aplicable;
  - publicar credenciales, datos personales o información confidencial en los *issues* o canales públicos;
  - presentar una versión modificada del Software como producto oficial de Transgenia.org;
  - enviar spam o contenido ilícito o abusivo por los canales de Transgenia.org, ni atacar o saturar su infraestructura.
- Ante conductas contrarias a esta sección, Transgenia.org podrá moderar o cerrar *issues*, bloquear cuentas en sus repositorios y canales, y suspender la atención al Usuario.
- El Usuario es responsable de revisar las acciones que su agente de IA ejecute sobre su instancia de Odoo. Se recomienda probarlas en el entorno local de pruebas o en una base de datos de pruebas antes de operar sobre producción, y contar con respaldos.

---

## 10. AUSENCIA DE GARANTÍA Y LIMITACIÓN DE RESPONSABILIDAD

### 10.1 Ausencia de garantía

- De conformidad con la Licencia MIT y en la medida en que lo permita la legislación aplicable, el Software se proporciona “tal cual”, sin garantía de ningún tipo, expresa o implícita, incluidas, entre otras, las garantías de comerciabilidad, idoneidad para un fin determinado y no infracción. Los Servicios gratuitos se prestan en las mismas condiciones. Esta exclusión, que reproduce el texto de la Licencia MIT, se interpreta conforme a la legislación mexicana y no afecta los derechos irrenunciables a que se refiere la sección 12.1.
- Los resultados que produzca un agente de IA con el Software son ayudas. El Usuario conserva la responsabilidad de revisarlos antes de aplicarlos en producción.

### 10.2 Limitación de responsabilidad

- En la máxima medida que permita la ley aplicable, Transgenia.org no será responsable de daños directos o indirectos, pérdida de datos, lucro cesante ni reclamaciones derivados del uso o de la imposibilidad de uso del Software o de los Servicios gratuitos, en los términos de la Licencia MIT y de estos Términos.
- Esta limitación no aplica a la responsabilidad por dolo o mala fe, cuya renuncia es nula conforme al artículo 2106 del Código Civil Federal, ni a la derivada de negligencia grave, ni a los supuestos en que la ley aplicable prohíba excluir o limitar la responsabilidad, y se entiende sin perjuicio de los derechos irrenunciables del Usuario que tenga el carácter de consumidor (sección 12.1).

---

## 11. CAMBIOS A LOS TÉRMINOS

- Transgenia.org podrá actualizar estos Términos. Cada versión se publicará en el repositorio del Software y en <https://transgenia.org>, con su número de versión y su fecha de emisión.
- Los cambios surtirán efecto a partir de su publicación. Los cambios sustanciales se anunciarán en el registro de cambios (`CHANGELOG`) del repositorio y surtirán efecto 15 días naturales después de su publicación.
- El uso continuado de los Servicios después de la entrada en vigor de una nueva versión implica su aceptación. Ningún cambio a estos Términos afecta la Licencia MIT de las versiones del Software ya distribuidas.
- Las dudas sobre los cambios a estos Términos y a los demás documentos legales y de privacidad pueden dirigirse a notificaciones@transgenia.org.

---

## 12. LEGISLACIÓN APLICABLE, JURISDICCIÓN Y PREVALENCIA NORMATIVA

### 12.1 Ley aplicable y jurisdicción

- Estos Términos se rigen e interpretan conforme a las leyes federales de los Estados Unidos Mexicanos, en particular la LFDA, la LFPPI, la LFPDPPP, el Código Civil Federal y, cuando se trate de actos de comercio, el Código de Comercio. Para cualquier controversia derivada de ellos, las partes se someten a los tribunales competentes de la Ciudad de México y renuncian a cualquier otro fuero que pudiera corresponderles por razón de su domicilio presente o futuro, salvo lo previsto en el párrafo siguiente.
- Cuando el Usuario tenga el carácter de consumidor en términos del artículo 2 de la Ley Federal de Protección al Consumidor (LFPC), conserva los derechos que esa ley le otorga, que son irrenunciables (artículo 1) y prevalecen sobre cualquier disposición en contrario de estos Términos, incluido el de acudir a la Procuraduría Federal del Consumidor (PROFECO). Lo anterior se entiende también sin perjuicio de las normas imperativas de protección de datos o de protección al consumidor que resulten aplicables al Usuario en su lugar de residencia.

### 12.2 Prevalencia y coordinación normativa

- En caso de conflicto entre las leyes mencionadas en estos Términos (LFDA, LFPPI, LFPDPPP, LFPC, Código Civil Federal, Código de Comercio, RGPD, DMCA u otras) y lo aquí pactado, se aplicarán las normas que resulten imperativas en la jurisdicción correspondiente, sin que ello implique la nulidad del resto de estos Términos. Las leyes extranjeras citadas se aplican sólo en la medida en que resulten aplicables.
- Si alguna disposición de estos Términos resulta nula o inaplicable, las demás conservarán su validez.
- Orden de prevalencia: (i) respecto del Software, la Licencia MIT; (ii) respecto de los servicios contratados, el Contrato Comercial Macro y sus anexos, cuando exista; y (iii) en lo demás, estos Términos.

### 12.3 Idioma

- La versión en español de estos Términos es la única con validez legal y prevalece. La versión en inglés es una traducción fiel, con la misma estructura y numeración, que se ofrece sólo por conveniencia; en caso de discrepancia, prevalece la versión en español.

---

## 13. ACEPTACIÓN

- Al descargar, instalar, acceder o utilizar el Software o los Servicios, el Usuario reconoce que ha leído, entendido y aceptado estos Términos en todo lo que se refiere a su relación con Transgenia.org.
- La aceptación por medios electrónicos constituye consentimiento expreso conforme al artículo 1803 del Código Civil Federal y, cuando se trate de actos de comercio, surte efectos conforme a los artículos 80 y 89 y siguientes del Código de Comercio.
- La aceptación de estos Términos no es condición para ejercer los derechos que otorga la Licencia MIT. Si el Usuario no está de acuerdo con ellos, puede seguir usando el Software conforme a la Licencia MIT, pero deberá abstenerse de usar los Servicios.

---

## 14. CONTACTO Y CANALES OFICIALES

- **Correo electrónico (asuntos técnicos y comerciales):** dev@transgenia.org
- **WhatsApp:** +52 55 8034 0405 (<https://wa.me/525580340405>)
- **Sitio web:** <https://transgenia.org>
- **Avisos legales y de privacidad (incluidas las solicitudes ARCO, de supresión y DMCA):** notificaciones@transgenia.org. Aviso de Privacidad: <https://transgenia.org/legal-privacidad.html>
- **Reportes de errores y solicitudes de funcionalidad:** *issues* del repositorio <https://github.com/Transgenia/MCP-Odoo-Tools-CE-EE-and-online>
- **Vulnerabilidades de seguridad:** conforme al archivo `SECURITY.md` del repositorio.

---

**Anexos referenciados (no exhaustivos):**

- Licencia MIT (archivo `LICENSE` del repositorio).
- Archivo `NOTICE` (componentes de terceros y sus licencias).
- Política de privacidad del *plugin* (`PRIVACY.md`) y política de seguridad (`SECURITY.md`).
- Aviso de Privacidad de Transgenia.org (<https://transgenia.org/legal-privacidad.html>).
- Licencias de terceros aplicables: GNU LGPL v3 (Odoo Community Edition); Odoo Enterprise Edition License v1.0 (Odoo Enterprise Edition); términos de servicio y suscripción de Odoo S.A. (Odoo Online); PostgreSQL License (PostgreSQL); y Licencia MIT (odoo-agent).

Estos Términos podrán ser actualizados conforme a la sección 11.

---
