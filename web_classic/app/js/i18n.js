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
        getLanguages: () => Object.entries(dictionaries).map(([code, data]) => ({ code, name: data.name }))
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
            completedValidations: "{completed}/{total} validaciones completadas · {consensus}",
            fullConsensus: "Consenso completo",
            partialConsensus: "Consenso parcial",
            validatorVotes: "Votos de validadores",
            orderId: "ID de Orden",
            progress: "Progreso",
            newsSummary: "Noticia (Resumen)",
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
            BLOCKCHAIN_PENDING: "Blockchain pendiente"
        },
        messages: {
            identityError: "Error de conexión con el servidor de identidad",
            writeNews: "Debes escribir o cargar una noticia",
            generatingAssertions: "Generando aserciones...",
            assertionsGenerated: "Aserciones generadas",
            importUrl: "Introduce una URL para importar",
            importError: "Error al importar la noticia. Revisa la consola.",
            enterOrderId: "Introduce un order_id.",
            loadingOrder: "Cargando detalles de la orden <strong>{orderId}</strong>...",
            orderNotFound: "Error: Order ID {orderId} no encontrada.",
            criticalOrderError: "Error crítico al cargar la orden.",
            listingOrders: "Listando todas las órdenes...",
            ordersLoaded: "Órdenes cargadas: {count}",
            listOrdersError: "Error al listar órdenes. Ver consola."
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
            completedValidations: "{completed}/{total} validations completed · {consensus}",
            fullConsensus: "Full consensus",
            partialConsensus: "Partial consensus",
            validatorVotes: "Validator votes",
            orderId: "Order ID",
            progress: "Progress",
            newsSummary: "News (Summary)",
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
            BLOCKCHAIN_PENDING: "Blockchain pending"
        },
        messages: {
            identityError: "Connection error with the identity server",
            writeNews: "You must write or load a news article",
            generatingAssertions: "Generating assertions...",
            assertionsGenerated: "Assertions generated",
            importUrl: "Enter a URL to import",
            importError: "Error importing the news article. Check the console.",
            enterOrderId: "Enter an order_id.",
            loadingOrder: "Loading order details for <strong>{orderId}</strong>...",
            orderNotFound: "Error: Order ID {orderId} not found.",
            criticalOrderError: "Critical error loading the order.",
            listingOrders: "Listing all orders...",
            ordersLoaded: "Orders loaded: {count}",
            listOrdersError: "Error listing orders. See console."
        }
    });

    document.addEventListener("DOMContentLoaded", () => applyTranslations(document));
})();
