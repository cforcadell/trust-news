(() => {
    const STORAGE_KEY = "trustnews.language";
    const DEFAULT_LANGUAGE = "es";
    const dictionaries = {};

    function getByPath(obj, path) {
        return String(path || "").split(".").reduce((acc, part) => acc && acc[part], obj);
    }

    function interpolate(text, params = {}) {
        return String(text).replace(/\{(\w+)\}/g, (_, key) => params[key] ?? "");
    }

    function currentLanguage() {
        const stored = localStorage.getItem(STORAGE_KEY);
        return dictionaries[stored] ? stored : DEFAULT_LANGUAGE;
    }

    function translate(key, params = {}) {
        const lang = currentLanguage();
        const value = getByPath(dictionaries[lang]?.messages, key)
            ?? getByPath(dictionaries[DEFAULT_LANGUAGE]?.messages, key)
            ?? key;
        return interpolate(value, params);
    }

    function applyTranslations(root = document) {
        const lang = currentLanguage();
        document.documentElement.lang = lang;

        root.querySelectorAll("[data-i18n]").forEach(el => {
            el.innerHTML = translate(el.dataset.i18n);
        });
        root.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
            el.setAttribute("placeholder", translate(el.dataset.i18nPlaceholder));
        });
        root.querySelectorAll("[data-i18n-title]").forEach(el => {
            el.setAttribute("title", translate(el.dataset.i18nTitle));
        });
        root.querySelectorAll("[data-i18n-aria-label]").forEach(el => {
            el.setAttribute("aria-label", translate(el.dataset.i18nAriaLabel));
        });
        root.querySelectorAll("[data-i18n-value]").forEach(el => {
            el.setAttribute("value", translate(el.dataset.i18nValue));
        });

        const selector = document.getElementById("languageSelector");
        if (selector) {
            const currentOptions = Array.from(selector.options).map(option => option.value).join("|");
            const registeredOptions = Object.keys(dictionaries).join("|");
            if (currentOptions !== registeredOptions) {
                selector.innerHTML = Object.entries(dictionaries)
                    .map(([code, data]) => `<option value="${code}">${data.name}</option>`)
                    .join("");
            }
            selector.value = lang;
        }
    }

    function registerLanguage(code, name, messages) {
        dictionaries[code] = { name, messages };
    }

    function setLanguage(code) {
        if (!dictionaries[code]) return;
        localStorage.setItem(STORAGE_KEY, code);
        applyTranslations(document);
        window.dispatchEvent(new CustomEvent("trustnews:languagechange", { detail: { language: code } }));
    }

    window.I18N = {
        registerLanguage,
        setLanguage,
        applyTranslations,
        t: translate,
        getLanguage: currentLanguage,
        getLanguages: () => Object.entries(dictionaries).map(([code, data]) => ({ code, name: data.name })),
        getCategoryIds: () => Object.keys(dictionaries[currentLanguage()]?.messages?.ui?.categoriesMap || {})
    };

    registerLanguage("es", "Castellano", {
        brand: { subtitle: "Consola de verificación" },
        nav: {
            verification: "Verificación News",
            newVerification: "Nueva Verificación Automática",
            orders: "Listado de Órdenes",
            searchOrders: "Buscar Órdenes",
            consistency: "Comprobar Consistencia",
            explorer: "Explorador",
            ipfs: "Buscar Documento (IPFS)",
            tx: "Buscar Transacciones",
            blocks: "Buscar Bloques",
            contract: "Buscar Post (Contract)",
            validators: "Validadores",
            cta: "+ Verificar nuevo contenido"
        },
        header: {
            title: "Consola de verificación",
            protectedSession: "● Sesión protegida",
            logout: "Salir",
            language: "Idioma"
        },
        sections: {
            verification: "Verificación",
            newVerification: "Nueva Verificación Automática",
            newVerificationHelp: "Importa una URL o pega el texto de una noticia para generar aserciones y publicar la orden.",
            newsUrl: "URL de la noticia a importar",
            importNews: "Importar Noticia",
            newsText: "Escribe la noticia aquí para publicar, o el texto a buscar.",
            generateAssertions: "Generar Aserciones",
            publishNews: "Publicar Noticia",
            clearNews: "Limpiar noticia",
            flow: "Flujo",
            flowValue: "Texto → Aserciones → Orden → Validación",
            output: "Salida",
            outputValue: "Reporte verificable con trazabilidad",
            orders: "Órdenes",
            orderHistory: "Historial de Órdenes",
            orderHistoryHelp: "Consulta el estado agregado de las verificaciones y accede al detalle de cada orden.",
            refreshList: "Refrescar Listado",
            viewAllOrders: "Ver órdenes de todos los clientes (Admin)",
            search: "Buscar",
            searchOrder: "Buscar Orden Específica",
            searchOrderHelp: "Introduce un order_id para revisar documento, aserciones, validaciones y eventos.",
            orderId: "Introduce el order_id",
            findOrder: "Buscar Orden",
            integrity: "Integridad",
            integrityCheck: "Check de Integridad con Ethereum",
            orderIdPlaceholder: "Introduce order Id",
            checkConsistency: "Comprobar Consistencia",
            ipfsSearch: "Búsqueda en IPFS",
            ipfsHash: "Introduce IPFS hash",
            findIpfs: "Buscar IPFS",
            txQuery: "Consulta de Transacciones",
            txHash: "Introduce transaction hash (ej: 0x55d2817a...)",
            findTx: "Buscar Transacción",
            blockQuery: "Consulta de Bloques",
            blockId: "Introduce block number o hash",
            findBlock: "Buscar Bloque",
            validatorsKicker: "Validators",
            validators: "Validadores",
            validatorsHelp: "Listado de validadores registrados en blockchain con configuración IPFS y detalle de validaciones.",
            refreshValidators: "Refrescar Validadores",
            postId: "Introduce post Id",
            findPost: "Buscar Post"
        },
        tabs: { assertions: "Aserciones", document: "Documento", validations: "Validaciones", events: "Eventos", summary: "Resumen", details: "Detalles" },
        ui: {
            evidence: "Evidencias", process: "Proceso", technical: "Técnico", date: "Fecha", validationMode: "Modo de validación",
            orderId: "ID de orden", assertionSummary: "Resumen de afirmaciones", totalCount: "{count} en total",
            weightedValidatorVote: "Voto ponderado de validadores", inFavor: "A favor", against: "En contra",
            noConclusion: "Sin conclusión", weightedTotal: "Total ponderado", validationSummary: "Resumen de validación",
            validationsCompleted: "Validaciones completadas", percentCompleted: "{percent}% completado", totalValidationTime: "Tiempo total de validación",
            inProgress: "En curso", processCompleted: "Proceso completado", pendingCount: "{count} pendientes",
            problematicAssertions: "Afirmaciones con problemas", viewAllAssertions: "Ver todas las afirmaciones →",
            newsSummary: "Resumen de la noticia", confirmed: "Confirmadas", disproved: "Desmentidas", inconclusive: "No concluyentes",
            confirmedHelp: "Afirmaciones respaldadas por evidencia fiable.", disprovedHelp: "Afirmaciones contradichas por la evidencia.",
            inconclusiveHelp: "No hay evidencia suficiente para determinar.", noProblematicAssertions: "No se han detectado afirmaciones problemáticas.",
            noNewsText: "No hay texto disponible.", noAssertions: "No hay afirmaciones disponibles.", assertionWithoutText: "Afirmación sin texto",
            result: "Resultado", validators: "Validadores", assertions: "Afirmaciones", status: "Estado", mode: "Modo",
            orderCreated: "Orden creada", assertionsRequested: "Aserciones solicitadas", evidenceSearch: "Búsqueda de evidencias",
            validations: "Validaciones", consensusResult: "Consenso / Resultado", document: "Documento", blockchain: "Blockchain",
            verificationCompleted: "Verificación completada", verificationInProgress: "Verificación en curso",
            completedExplanation: "El consenso está cerrado y el resultado definitivo ya está disponible.",
            progressExplanation: "Estamos validando la noticia y actualizando el resultado a medida que llegan nuevas respuestas.",
            completed: "Completada", lastUpdate: "Última actualización", currentActivity: "Qué está ocurriendo ahora",
            allValidationsReceived: "Todas las validaciones esperadas han llegado", waitingValidations: "Esperando {count} validaciones restantes",
            waitingUpdate: "Esperando la siguiente actualización", consensusClosed: "El consenso ya se ha cerrado",
            consensusOpen: "El consenso aún no puede cerrarse", definitiveResult: "El resultado ya es definitivo",
            provisionalMayChange: "El resultado provisional puede variar", receivedValidations: "Validaciones recibidas",
            provisionalResult: "Resultado provisional", provisional: "Provisional",
            provisionalNotice: "Este resultado puede cambiar hasta alcanzar el consenso final.", elapsedTime: "Tiempo transcurrido",
            currentStatus: "Estado actual", consensusComplete: "Consenso cerrado", updating: "Actualizando",
            statusChanges: "Cambios de estado", untilNow: "Hasta ahora",
            autoSummaryNotice: "Cuando el proceso alcance el estado final, la vista cambiará automáticamente a la pestaña Resumen.",
            noValidationYet: "Todavía no se ha recibido ninguna validación", lastValidationSeconds: "Última validación recibida hace {count} s",
            lastValidationMinutes: "Última validación recibida hace {count} min", lightUnavailable: "Detalle blockchain/IPFS no disponible para validaciones en modo Light.",
            ipfsDocument: "Documento IPFS", backToSearch: "← Volver al buscador", validationModeLabel: "Modo de validación",
            blockchainAuditLabel: "Auditar y trazabilidad con Blockchain",
            blockchainAuditTooltip: "Al activar esta opción, los documentos de la verificación se publican en IPFS y su trazabilidad queda registrada en blockchain para facilitar su auditoría e integridad.",
            smartContractPost: "Smart Contract (Post)", assertion: "Aserción", category: "Categoría", publishWithAssertions: "Publicar con Aserciones",
            publishTextRequired: "Introduce un texto para verificar.", publishing: "Publicando...", publishError: "Error al publicar la noticia. Inténtalo de nuevo.",
            newsPublished: "Noticia publicada. Iniciando polling para Order ID: {orderId}", assertionsContainerMissing: "No se encontró el contenedor de aserciones.",
            assertionRequired: "Debes tener al menos una aserción", publishAssertionsError: "Error al publicar la noticia con aserciones",
            quotaReached: "Límite alcanzado: no te quedan cuotas para generar aserciones.", assertionsServiceError: "Error al conectar con el servicio de aserciones",
            unknownError: "Error desconocido", errorMessage: "Mensaje", connectionJsonError: "Error de conexión o JSON inválido: {message}",
            noData: "No hay datos disponibles.", pageOf: "Página {page} / {total}", showingOrders: "Mostrando {shown} de {total} órdenes",
            yes: "Sí", noRecord: "No consta", noDescription: "Sin descripción", viewEvidence: "Ver evidencias ({count})",
            noValidatorValidations: "No hay validaciones para este validador.", noNewsTextShort: "Sin texto de noticia",
            order: "Orden", viewOrder: "Ver orden", categories: "Categorías", actions: "Acciones", name: "Nombre", type: "Tipo",
            provider: "Proveedor", model: "Modelo", ipfsConfig: "Configuración IPFS", viewValidations: "Ver validaciones",
            loadingValidators: "Cargando validadores...", noValidators: "No hay validadores registrados.", validatorsLoadError: "Error cargando validadores.",
            loadingConfig: "Cargando configuración...", validatorConfig: "Configuración del validador", requestsSent: "Solicitudes enviadas",
            successfulResponses: "Respuestas correctas", averageResponseTime: "Tiempo medio de respuesta", activeDate: "Fecha de activación",
            updatedDate: "Fecha de actualización", endDate: "Fecha de finalización", viewCompletedValidations: "Ver validaciones realizadas",
            validatorConfigError: "Error cargando configuración del validador.", loadingValidations: "Cargando validaciones...",
            completedValidationsTitle: "Validaciones realizadas", validatorValidationsError: "Error cargando validaciones del validador.",
            requestResponseTime: "Tiempo petición-respuesta", transactionHash: "Hash de transacción", invalidDate: "Fecha inválida",
            visualStageFlow: "Flujo visual de etapas ({mode})", processProgress: "Progreso del proceso", stagesReached: "{reached} / {total} etapas alcanzadas",
            currentPhase: "Fase actual", recentActivity: "Actividad reciente", changesCount: "{count} cambios", noActivity: "Sin actividad registrada.",
            sinceOrderCreation: "Desde la creación de la orden", previous: "‹ Anterior", next: "Siguiente ›", created: "Creado", updated: "Actualizado", pending: "Pendientes", textHash: "Hash texto",
            viewDetail: "Ver detalle →", noOrderValidations: "No hay validaciones disponibles para esta orden.", noEvents: "No hay eventos registrados.", noAssertionsAvailable: "No hay aserciones disponibles.",
            clearTrend: "Tendencia confirmada", disprovedTrend: "Tendencia desmentida", noClearTrend: "Sin tendencia clara",
            field: "Campo", value: "Valor", blockTransactions: "Transacciones del bloque", ipfsContent: "Contenido IPFS",
            enterIpfsHash: "Introduce un hash de IPFS", searchingIpfs: "Buscando contenido en IPFS...", contentRetrieved: "Contenido recuperado.", ipfsSearchError: "Error al buscar en IPFS.", ipfsContentError: "Error al obtener el contenido desde IPFS.",
            enterTxHash: "Introduce un hash de transacción", searchingTransaction: "Buscando transacción...", transactionFound: "Transacción encontrada.", transactionSearchError: "Error al buscar la transacción.", invalidTransaction: "Error al obtener la transacción o el hash no es válido.",
            enterBlock: "Introduce un número o hash de bloque", searchingBlock: "Buscando bloque...", blockFound: "Bloque encontrado.", blockSearchError: "Error al buscar el bloque.", invalidBlock: "Error al obtener el bloque o el ID/hash no es válido.",
            enterContract: "Introduce una dirección o nombre de contrato", searchingContract: "Buscando contrato...", contractFound: "Contrato encontrado.", contractSearchError: "Error al buscar el contrato.", invalidContract: "Error al obtener el contrato o el ID no es válido.",
            text: "Texto", domain: "Dominio", reputation: "Reputación", verdict: "Veredicto", searchTextRequired: "Introduce un texto a buscar.",
            categoriesMap: { "1": "ECONOMÍA", "2": "DEPORTES", "3": "POLÍTICA", "4": "TECNOLOGÍA", "5": "SALUD", "6": "ENTRETENIMIENTO", "7": "CIENCIA", "8": "CULTURA", "9": "MEDIO AMBIENTE", "10": "SOCIAL" },
            validatorTypes: { "1": "LLM memoria", "2": "LLM con búsqueda", "3": "RAG con evidencias", "4": "Determinista", "5": "Humano" },
            searchingPrevious: "Buscando verificaciones previas...", resultsFound: "Se encontraron {count} resultados.", searchError: "Error de conexión o datos inválidos al buscar.", resultsLoadError: "Error al cargar los resultados.",
            eventsCount: "Eventos ({count} total)", localServiceError: "Error al conectar con el servicio local.", detailLabel: "Detalle"
        },
        summary: {
            verified: "Verificada",
            partial: "Parcialmente verificada",
            contradicted: "Desmentida",
            inconclusive: "No concluyente",
            pending: "Pendiente",
            confirmedOne: "confirmada",
            confirmedMany: "confirmadas",
            disprovedOne: "desmentida",
            disprovedMany: "desmentidas",
            inconclusiveOne: "no concluyente",
            inconclusiveMany: "no concluyentes",
            confirmedAmongVerified: "Confirmadas entre las verificadas: {confirmed}/{known}",
            noVerifiedAssertions: "Sin afirmaciones verificadas todavía",
            pendingConclusion: "La verificación sigue en curso: {completed}/{total} validaciones de IA completadas.",
            verifiedConclusion: "La noticia queda verificada: {breakdown}. No se detectan afirmaciones desmentidas.",
            disprovedConclusion: "La noticia queda desmentida: predominan las afirmaciones rechazadas por los validadores. Resultado: {breakdown}.",
            partialConclusion: "La noticia contiene afirmaciones mezcladas: {breakdown}. No debe considerarse plenamente fiable.",
            inconclusiveConclusion: "La verificación no permite una conclusión firme: {breakdown}. Conviene revisar las evidencias antes de decidir.",
            verificationResult: "Resultado de verificación",
            resultByAssertion: "Resultado por afirmación",
            confirmed: "Confirmadas",
            disproved: "Desmentidas",
            notConclusive: "No concluyentes",
            of: "de",
            completedValidations: "Validaciones completadas · {completed}/{total} recibidas/emitidas · {consensus}",
            completedValidationsWithDuration: "Validaciones completadas · {completed}/{total} recibidas/emitidas · {consensus} · Tiempo total: {duration}",
            fullConsensus: "Consenso completo",
            partialConsensus: "Consenso parcial",
            validatorVotes: "Votos de validadores",
            orderId: "ID de Orden",
            progress: "Progreso",
            newsSummary: "Noticia (Resumen)",
            showMore: "Mostrar más",
            showLess: "Mostrar menos",
            expandNewsSummaryHint: "Ampliar el resumen completo",
            collapseNewsSummaryHint: "Contraer el resumen a cinco líneas",
            validationTotalTime: "Tiempo total de validación",
            pendingValidations: "Validaciones pendientes",
            totalValidations: "Validaciones totales",
            confirmedAssertions: "Afirmaciones confirmadas",
            disprovedAssertions: "Afirmaciones desmentidas",
            inconclusiveVotes: "Votos no concluyentes"
        },
        status: {
            VALIDATED: "Completada",
            PENDING: "Pendiente",
            VALIDATION_PENDING: "Validación pendiente",
            ASSERTIONS_REQUESTED: "Aserciones solicitadas",
            DOCUMENT_CREATED: "Documento creado",
            IPFS_PENDING: "IPFS pendiente",
            IPFS_UPLOADED: "IPFS subido",
            BLOCKCHAIN_PENDING: "Blockchain pendiente",
            CREATED: "Orden creada", ASSERTIONS_NOT_AVAILABLE: "Aserciones no disponibles", QUOTA_EXCEDED: "Cuota excedida",
            NO_VALIDATORS_AVAILABLE: "Sin validadores disponibles"
        },
        messages: {
            identityError: "Error de conexión con el servidor de identidad",
            writeNews: "Debes escribir o cargar una noticia",
            generatingAssertions: "Generando aserciones...",
            assertionsGenerated: "Aserciones generadas",
            assertionStageAnalyzing: "Analizando el contenido",
            assertionStageExtracting: "Extrayendo afirmaciones verificables",
            assertionStagePreparing: "Preparando los resultados",
            assertionElapsed: "Tiempo transcurrido: {count} s",
            assertionsTakingLonger: "La generación continúa. Los textos extensos pueden tardar un poco más.",
            assertionsGeneratedCount: "Aserciones generadas: {count}",
            assertionsReviewHelp: "Revisa y edita las aserciones antes de publicar la noticia.",
            noAssertionsFound: "No se generaron aserciones.",
            noAssertionsFoundHelp: "Puedes reintentarlo o añadir las aserciones manualmente.",
            assertionGenerationErrorTitle: "No se pudieron generar las aserciones",
            assertionTimeoutError: "La generación superó el tiempo de espera de {seconds} segundos. Puedes volver a intentarlo sin perder el texto.",
            assertionAuthenticationError: "La sesión no pudo validarse. Vuelve a iniciar sesión y reintenta la operación.",
            assertionServerError: "El servicio de aserciones no está disponible temporalmente. Inténtalo de nuevo en unos instantes.",
            assertionInvalidResponseError: "El servicio devolvió una respuesta que no se pudo interpretar.",
            assertionRequestError: "La solicitud no pudo completarse (error {status}).",
            assertionNetworkError: "No se pudo conectar con el servicio de aserciones. Comprueba la conexión y vuelve a intentarlo.",
            retry: "Reintentar",
            verificationChecking: "Verificación en curso",
            verificationElapsed: "Actualizando el estado automáticamente · {count} s transcurridos",
            verificationConnectionRetry: "Problema temporal de conexión · intento {current} de {total}",
            verificationOrderPreserved: "La orden {orderId} sigue disponible mientras se recupera la conexión.",
            verificationTimeoutTitle: "La verificación está tardando más de lo esperado",
            verificationTimeoutError: "No se ha confirmado un estado final después de {minutes} minutos. La orden {orderId} sigue disponible y puedes reanudar la comprobación.",
            verificationConnectionErrorTitle: "No se pudo actualizar la verificación",
            verificationConnectionError: "Han fallado varios intentos de conexión. La orden {orderId} se conserva y puedes reintentar la comprobación.",
            verificationTerminalErrorTitle: "La verificación terminó con un error",
            verificationTerminalError: "La orden {orderId} ha finalizado con el estado {status}. Revisa el detalle del proceso.",
            retryVerification: "Reintentar comprobación",
            orderLoadTimeoutError: "La consulta de la orden superó el tiempo de espera de {seconds} segundos.",
            importUrl: "Introduce una URL para importar",
            importError: "Error al importar la noticia. Revisa la consola.",
            enterOrderId: "Introduce un order_id.",
            loadingOrder: "Cargando detalles de la orden <strong>{orderId}</strong>...",
            orderNotFound: "Error: Order ID {orderId} no encontrada.",
            criticalOrderError: "Error crítico al cargar la orden.",
            listingOrders: "Listando todas las órdenes...",
            ordersLoaded: "Órdenes cargadas: {count}",
            listOrdersError: "Error al listar órdenes. Ver consola.",
            noValidationsRegistered: "Sin validaciones registradas."
        }
    });

    registerLanguage("en", "English", {
        brand: { subtitle: "Verification Console" },
        nav: {
            verification: "News Verification",
            newVerification: "New Automatic Verification",
            orders: "Order List",
            searchOrders: "Search Orders",
            consistency: "Check Consistency",
            explorer: "Explorer",
            ipfs: "Search Document (IPFS)",
            tx: "Search Transactions",
            blocks: "Search Blocks",
            contract: "Search Post (Contract)",
            validators: "Validators",
            cta: "+ Verify new content"
        },
        header: {
            title: "Verification console",
            protectedSession: "● Protected session",
            logout: "Log out",
            language: "Language"
        },
        sections: {
            verification: "Verification",
            newVerification: "New Automatic Verification",
            newVerificationHelp: "Import a URL or paste a news article to generate assertions and publish the order.",
            newsUrl: "News URL to import",
            importNews: "Import News",
            newsText: "Write the news article here to publish, or the text to search for.",
            generateAssertions: "Generate Assertions",
            publishNews: "Publish News",
            clearNews: "Clear news",
            flow: "Flow",
            flowValue: "Text → Assertions → Order → Validation",
            output: "Output",
            outputValue: "Verifiable report with traceability",
            orders: "Orders",
            orderHistory: "Order History",
            orderHistoryHelp: "Review the aggregated status of verifications and open each order detail.",
            refreshList: "Refresh List",
            viewAllOrders: "View orders from all clients (Admin)",
            search: "Search",
            searchOrder: "Search Specific Order",
            searchOrderHelp: "Enter an order_id to review document, assertions, validations and events.",
            orderId: "Enter the order_id",
            findOrder: "Search Order",
            integrity: "Integrity",
            integrityCheck: "Ethereum Integrity Check",
            orderIdPlaceholder: "Enter order Id",
            checkConsistency: "Check Consistency",
            ipfsSearch: "IPFS Search",
            ipfsHash: "Enter IPFS hash",
            findIpfs: "Search IPFS",
            txQuery: "Transaction Query",
            txHash: "Enter transaction hash (e.g. 0x55d2817a...)",
            findTx: "Search Transaction",
            blockQuery: "Block Query",
            blockId: "Enter block number or hash",
            findBlock: "Search Block",
            validatorsKicker: "Validators",
            validators: "Validators",
            validatorsHelp: "List of validators registered on blockchain with IPFS configuration and validation details.",
            refreshValidators: "Refresh Validators",
            postId: "Enter post Id",
            findPost: "Search Post"
        },
        tabs: { assertions: "Assertions", document: "Document", validations: "Validations", events: "Events", summary: "Summary", details: "Details" },
        ui: {
            evidence: "Evidence", process: "Process", technical: "Technical", date: "Date", validationMode: "Validation mode",
            orderId: "Order ID", assertionSummary: "Assertion summary", totalCount: "{count} total",
            weightedValidatorVote: "Weighted validator vote", inFavor: "In favor", against: "Against",
            noConclusion: "No conclusion", weightedTotal: "Weighted total", validationSummary: "Validation summary",
            validationsCompleted: "Validations completed", percentCompleted: "{percent}% completed", totalValidationTime: "Total validation time",
            inProgress: "In progress", processCompleted: "Process completed", pendingCount: "{count} pending",
            problematicAssertions: "Problematic assertions", viewAllAssertions: "View all assertions →",
            newsSummary: "News summary", confirmed: "Confirmed", disproved: "Disproved", inconclusive: "Inconclusive",
            confirmedHelp: "Assertions supported by reliable evidence.", disprovedHelp: "Assertions contradicted by the evidence.",
            inconclusiveHelp: "There is not enough evidence to decide.", noProblematicAssertions: "No problematic assertions were detected.",
            noNewsText: "No text is available.", noAssertions: "No assertions are available.", assertionWithoutText: "Assertion without text",
            result: "Result", validators: "Validators", assertions: "Assertions", status: "Status", mode: "Mode",
            orderCreated: "Order created", assertionsRequested: "Assertions requested", evidenceSearch: "Evidence search",
            validations: "Validations", consensusResult: "Consensus / Result", document: "Document", blockchain: "Blockchain",
            verificationCompleted: "Verification completed", verificationInProgress: "Verification in progress",
            completedExplanation: "Consensus is closed and the final result is now available.",
            progressExplanation: "We are validating the news item and updating the result as new responses arrive.",
            completed: "Completed", lastUpdate: "Last update", currentActivity: "What is happening now",
            allValidationsReceived: "All expected validations have arrived", waitingValidations: "Waiting for {count} remaining validations",
            waitingUpdate: "Waiting for the next update", consensusClosed: "Consensus has been closed",
            consensusOpen: "Consensus cannot be closed yet", definitiveResult: "The result is now final",
            provisionalMayChange: "The provisional result may change", receivedValidations: "Validations received",
            provisionalResult: "Provisional result", provisional: "Provisional",
            provisionalNotice: "This result may change until final consensus is reached.", elapsedTime: "Elapsed time",
            currentStatus: "Current status", consensusComplete: "Consensus closed", updating: "Updating",
            statusChanges: "Status changes", untilNow: "So far",
            autoSummaryNotice: "When the process reaches its final status, the view will automatically switch to the Summary tab.",
            noValidationYet: "No validation has been received yet", lastValidationSeconds: "Last validation received {count} s ago",
            lastValidationMinutes: "Last validation received {count} min ago", lightUnavailable: "Blockchain/IPFS details are unavailable for Light mode validations.",
            ipfsDocument: "IPFS document", backToSearch: "← Back to search", validationModeLabel: "Validation mode",
            blockchainAuditLabel: "Audit and traceability with Blockchain",
            blockchainAuditTooltip: "When enabled, verification documents are published to IPFS and their traceability is recorded on blockchain to support auditing and integrity.",
            smartContractPost: "Smart Contract (Post)", assertion: "Assertion", category: "Category", publishWithAssertions: "Publish with Assertions",
            publishTextRequired: "Enter text to verify.", publishing: "Publishing...", publishError: "Error publishing the news item. Try again.",
            newsPublished: "News published. Starting polling for Order ID: {orderId}", assertionsContainerMissing: "The assertions container was not found.",
            assertionRequired: "You must have at least one assertion", publishAssertionsError: "Error publishing the news item with assertions",
            quotaReached: "Quota reached: you have no assertion-generation quota left.", assertionsServiceError: "Could not connect to the assertions service",
            unknownError: "Unknown error", errorMessage: "Message", connectionJsonError: "Connection error or invalid JSON: {message}",
            noData: "No data available.", pageOf: "Page {page} / {total}", showingOrders: "Showing {shown} of {total} orders",
            yes: "Yes", noRecord: "Not specified", noDescription: "No description", viewEvidence: "View evidence ({count})",
            noValidatorValidations: "There are no validations for this validator.", noNewsTextShort: "No news text",
            order: "Order", viewOrder: "View order", categories: "Categories", actions: "Actions", name: "Name", type: "Type",
            provider: "Provider", model: "Model", ipfsConfig: "IPFS Config", viewValidations: "View validations",
            loadingValidators: "Loading validators...", noValidators: "No validators are registered.", validatorsLoadError: "Error loading validators.",
            loadingConfig: "Loading configuration...", validatorConfig: "Validator configuration", requestsSent: "Requests sent",
            successfulResponses: "Successful responses", averageResponseTime: "Average response time", activeDate: "Active date",
            updatedDate: "Updated date", endDate: "End date", viewCompletedValidations: "View completed validations",
            validatorConfigError: "Error loading validator configuration.", loadingValidations: "Loading validations...",
            completedValidationsTitle: "Completed validations", validatorValidationsError: "Error loading validator validations.",
            requestResponseTime: "Request-response time", transactionHash: "Transaction hash", invalidDate: "Invalid date",
            visualStageFlow: "Visual stage flow ({mode})", processProgress: "Process progress", stagesReached: "{reached} / {total} stages reached",
            currentPhase: "Current phase", recentActivity: "Recent activity", changesCount: "{count} changes", noActivity: "No activity recorded.",
            sinceOrderCreation: "Since the order was created", previous: "‹ Previous", next: "Next ›", created: "Created", updated: "Updated", pending: "Pending", textHash: "Text hash",
            viewDetail: "View detail →", noOrderValidations: "No validations are available for this order.", noEvents: "No events recorded.", noAssertionsAvailable: "No assertions are available.",
            clearTrend: "Confirmed trend", disprovedTrend: "Disproved trend", noClearTrend: "No clear trend",
            field: "Field", value: "Value", blockTransactions: "Block transactions", ipfsContent: "IPFS content",
            enterIpfsHash: "Enter an IPFS hash", searchingIpfs: "Searching IPFS content...", contentRetrieved: "Content retrieved.", ipfsSearchError: "Error searching IPFS.", ipfsContentError: "Error retrieving content from IPFS.",
            enterTxHash: "Enter a transaction hash", searchingTransaction: "Searching transaction...", transactionFound: "Transaction found.", transactionSearchError: "Error searching for the transaction.", invalidTransaction: "Could not retrieve the transaction or the hash is invalid.",
            enterBlock: "Enter a block number or hash", searchingBlock: "Searching block...", blockFound: "Block found.", blockSearchError: "Error searching for the block.", invalidBlock: "Could not retrieve the block or the ID/hash is invalid.",
            enterContract: "Enter a contract address or name", searchingContract: "Searching contract...", contractFound: "Contract found.", contractSearchError: "Error searching for the contract.", invalidContract: "Could not retrieve the contract or the ID is invalid.",
            text: "Text", domain: "Domain", reputation: "Reputation", verdict: "Verdict", searchTextRequired: "Enter text to search.",
            categoriesMap: { "1": "ECONOMY", "2": "SPORTS", "3": "POLITICS", "4": "TECHNOLOGY", "5": "HEALTH", "6": "ENTERTAINMENT", "7": "SCIENCE", "8": "CULTURE", "9": "ENVIRONMENT", "10": "SOCIAL" },
            validatorTypes: { "1": "Memory LLM", "2": "Search LLM", "3": "Evidence RAG", "4": "Deterministic", "5": "Human" },
            searchingPrevious: "Searching previous verifications...", resultsFound: "{count} results found.", searchError: "Connection error or invalid search data.", resultsLoadError: "Error loading results.",
            eventsCount: "Events ({count} total)", localServiceError: "Error connecting to the local service.", detailLabel: "Detail"
        },
        summary: {
            verified: "Verified",
            partial: "Partially verified",
            contradicted: "Disproved",
            inconclusive: "Inconclusive",
            pending: "Pending",
            confirmedOne: "confirmed",
            confirmedMany: "confirmed",
            disprovedOne: "disproved",
            disprovedMany: "disproved",
            inconclusiveOne: "inconclusive",
            inconclusiveMany: "inconclusive",
            confirmedAmongVerified: "Confirmed among verified assertions: {confirmed}/{known}",
            noVerifiedAssertions: "No verified assertions yet",
            pendingConclusion: "Verification is still in progress: {completed}/{total} AI validations completed.",
            verifiedConclusion: "The news item is verified: {breakdown}. No disproved assertions were detected.",
            disprovedConclusion: "The news item is disproved: rejected assertions predominate among validators. Result: {breakdown}.",
            partialConclusion: "The news item contains mixed assertions: {breakdown}. It should not be considered fully reliable.",
            inconclusiveConclusion: "Verification does not allow a firm conclusion: {breakdown}. Review the evidence before deciding.",
            verificationResult: "Verification result",
            resultByAssertion: "Result by assertion",
            confirmed: "Confirmed",
            disproved: "Disproved",
            notConclusive: "Inconclusive",
            of: "of",
            completedValidations: "Validations completed · {completed}/{total} received/issued · {consensus}",
            completedValidationsWithDuration: "Validations completed · {completed}/{total} received/issued · {consensus} · Total time: {duration}",
            fullConsensus: "Full consensus",
            partialConsensus: "Partial consensus",
            validatorVotes: "Validator votes",
            orderId: "Order ID",
            progress: "Progress",
            newsSummary: "News (Summary)",
            showMore: "Show more",
            showLess: "Show less",
            expandNewsSummaryHint: "Expand the full summary",
            collapseNewsSummaryHint: "Collapse the summary to five lines",
            validationTotalTime: "Total validation time",
            pendingValidations: "Pending validations",
            totalValidations: "Total validations",
            confirmedAssertions: "Confirmed assertions",
            disprovedAssertions: "Disproved assertions",
            inconclusiveVotes: "Inconclusive votes"
        },
        status: {
            VALIDATED: "Completed",
            PENDING: "Pending",
            VALIDATION_PENDING: "Validation pending",
            ASSERTIONS_REQUESTED: "Assertions requested",
            DOCUMENT_CREATED: "Document created",
            IPFS_PENDING: "IPFS pending",
            IPFS_UPLOADED: "IPFS uploaded",
            BLOCKCHAIN_PENDING: "Blockchain pending",
            CREATED: "Order created", ASSERTIONS_NOT_AVAILABLE: "Assertions unavailable", QUOTA_EXCEDED: "Quota exceeded",
            NO_VALIDATORS_AVAILABLE: "No validators available"
        },
        messages: {
            identityError: "Connection error with the identity server",
            writeNews: "You must write or load a news article",
            generatingAssertions: "Generating assertions...",
            assertionsGenerated: "Assertions generated",
            assertionStageAnalyzing: "Analyzing the content",
            assertionStageExtracting: "Extracting verifiable claims",
            assertionStagePreparing: "Preparing the results",
            assertionElapsed: "Elapsed time: {count} s",
            assertionsTakingLonger: "Generation is still running. Longer texts may take a little more time.",
            assertionsGeneratedCount: "Assertions generated: {count}",
            assertionsReviewHelp: "Review and edit the assertions before publishing the news item.",
            noAssertionsFound: "No assertions were generated.",
            noAssertionsFoundHelp: "You can retry or add assertions manually.",
            assertionGenerationErrorTitle: "Assertions could not be generated",
            assertionTimeoutError: "Generation exceeded the {seconds}-second time limit. You can retry without losing the text.",
            assertionAuthenticationError: "The session could not be validated. Sign in again and retry the operation.",
            assertionServerError: "The assertions service is temporarily unavailable. Try again in a few moments.",
            assertionInvalidResponseError: "The service returned a response that could not be interpreted.",
            assertionRequestError: "The request could not be completed (error {status}).",
            assertionNetworkError: "Could not connect to the assertions service. Check the connection and try again.",
            retry: "Retry",
            verificationChecking: "Verification in progress",
            verificationElapsed: "Updating the status automatically · {count} s elapsed",
            verificationConnectionRetry: "Temporary connection problem · attempt {current} of {total}",
            verificationOrderPreserved: "Order {orderId} remains available while the connection recovers.",
            verificationTimeoutTitle: "Verification is taking longer than expected",
            verificationTimeoutError: "No final status was confirmed after {minutes} minutes. Order {orderId} remains available and you can resume checking.",
            verificationConnectionErrorTitle: "The verification could not be updated",
            verificationConnectionError: "Several connection attempts failed. Order {orderId} is preserved and you can retry checking.",
            verificationTerminalErrorTitle: "Verification ended with an error",
            verificationTerminalError: "Order {orderId} finished with status {status}. Review the process details.",
            retryVerification: "Retry checking",
            orderLoadTimeoutError: "The order request exceeded the {seconds}-second time limit.",
            importUrl: "Enter a URL to import",
            importError: "Error importing the news article. Check the console.",
            enterOrderId: "Enter an order_id.",
            loadingOrder: "Loading order details for <strong>{orderId}</strong>...",
            orderNotFound: "Error: Order ID {orderId} not found.",
            criticalOrderError: "Critical error loading the order.",
            listingOrders: "Listing all orders...",
            ordersLoaded: "Orders loaded: {count}",
            listOrdersError: "Error listing orders. See console.",
            noValidationsRegistered: "No validations registered."
        }
    });

    document.addEventListener("DOMContentLoaded", () => applyTranslations(document));
})();
