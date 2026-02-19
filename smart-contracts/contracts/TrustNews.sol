// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TrustNews {

    // ======================================
    // ENUMS & STATE
    // ======================================

    enum evaluation {
        Unknown,
        True,
        False
    }

    address public owner;
    uint256 public postCounter;

    constructor() {
        owner = msg.sender;
    }

    // ======================================
    // STRUCTS
    // ======================================

    struct Validator {
        string domain;
        uint256 reputation;
        bool exists;
    }

    struct Multihash {
        bytes1 hash_function;
        bytes1 hash_size;
        bytes32 digest;
    }

    struct Validation {
        address validator;
        evaluation veredict;
        Multihash document;
    }

    struct Asertion {
        uint256 categoryId;
        Validation[] validations;
        mapping(address => uint256) validationIndex; // index + 1
    }

    struct Post {
        Asertion[] asertions;
        Multihash document;
        address publisher;
    }

    // ===== Views =====

    struct ValidationView {
        address validatorAddress;
        string domain;
        uint256 reputation;
        evaluation veredict;
        Multihash document;
    }

    struct AsertionView {
        uint256 categoryId;
        ValidationView[] validations;
    }

    // ======================================
    // STORAGE
    // ======================================

    mapping(address => Validator) public validators;
    mapping(address => uint256[]) public validatorCategories;
    mapping(uint256 => address[]) public validatorsByCategory;

    mapping(uint256 => string) public categories;

    mapping(uint256 => Post) public postsById;
    mapping(bytes32 => uint256) public postsCid;

    // ======================================
    // EVENTS
    // ======================================



    // Se emite por CADA validador asignado a una aserción
    event ValidationRequested(
        uint256 postId,
        Multihash postDocument,
        uint256 asertionIndex,
        address indexed validator
    );

    // Se emite cuando un validador registra o actualiza una validación
    event ValidationSubmitted(
        uint256 postId,
        Multihash postDocument,
        uint256 asertionIndex,
        address validator,
        Multihash validationDocument
    );

    event RegisterNewResult(
        uint256  postId,
        Multihash hash_ipfs,
        address[][] validatorAddressesByAsertion
    );


    // ======================================
    // PUBLICACIONES
    // ======================================

    function registerNew(
        Multihash memory hash_ipfs,
        uint256[] memory categoryIds
    )
        public
        returns (
            uint256 postId,
            address[][] memory validatorAddressesByAsertion
        )
    {
        require(categoryIds.length > 0, "No categories");

        postId = ++postCounter;

        Post storage p = postsById[postId];
        p.document = hash_ipfs;
        p.publisher = msg.sender;

        uint256 n = categoryIds.length;
        validatorAddressesByAsertion = new address[][](n);

        for (uint256 i = 0; i < n; i++) {
            uint256 catId = categoryIds[i];
            require(bytes(categories[catId]).length != 0, "Category not exists");

            p.asertions.push();
            p.asertions[i].categoryId = catId;

            address[] storage v = validatorsByCategory[catId];
            validatorAddressesByAsertion[i] = v;

            // 🔔 Evento POR CADA VALIDADOR
            for (uint256 j = 0; j < v.length; j++) {
                emit ValidationRequested(
                    postId,
                    p.document,
                    i,
                    v[j]
                );
            }
        }
        emit RegisterNewResult(postId, hash_ipfs, validatorAddressesByAsertion);
        postsCid[hash_ipfs.digest] = postId;


    }

    // ======================================
    // CONSULTAS
    // ======================================

    function getNewByCid(Multihash memory hash_cid)
        public
        view
        returns (uint256)
    {
        return postsCid[hash_cid.digest];
    }

    function getPostFlat(uint256 postId)
        public
        view
        returns (Multihash memory document, address publisher)
    {
        Post storage p = postsById[postId];
        return (p.document, p.publisher);
    }

    function getAsertionsWithValidations(uint256 postId)
        public
        view
        returns (AsertionView[] memory)
    {
        Post storage p = postsById[postId];
        uint256 n = p.asertions.length;

        AsertionView[] memory result = new AsertionView[](n);

        for (uint256 i = 0; i < n; i++) {
            Asertion storage a = p.asertions[i];
            uint256 m = a.validations.length;

            ValidationView[] memory validations = new ValidationView[](m);

            for (uint256 j = 0; j < m; j++) {
                Validation storage v = a.validations[j];
                Validator storage val = validators[v.validator];

                validations[j] = ValidationView({
                    validatorAddress: v.validator,
                    domain: val.domain,
                    reputation: val.reputation,
                    veredict: v.veredict,
                    document: v.document
                });
            }

            result[i] = AsertionView({
                categoryId: a.categoryId,
                validations: validations
            });
        }

        return result;
    }

    // ======================================
    // VALIDADORES Y CATEGORÍAS
    // ======================================

    function addCategory(uint256 id, string memory description) public {
        require(msg.sender == owner, "Only owner");
        require(bytes(categories[id]).length == 0, "Category exists");
        categories[id] = description;
    }

    function registerValidator(
        string memory domain,
        uint256[] memory categoryIds
    ) public {
        require(!validators[msg.sender].exists, "Already validator");
        require(bytes(domain).length != 0, "Invalid domain");
        require(categoryIds.length > 0, "No categories");

        validators[msg.sender] = Validator({
            domain: domain,
            reputation: 0,
            exists: true
        });

        validatorCategories[msg.sender] = categoryIds;

        for (uint256 i = 0; i < categoryIds.length; i++) {
            uint256 catId = categoryIds[i];
            require(bytes(categories[catId]).length != 0, "Category not exists");
            validatorsByCategory[catId].push(msg.sender);
        }
    }

    function unregisterValidator() public {
        require(validators[msg.sender].exists, "Not validator");

        uint256[] storage cats = validatorCategories[msg.sender];

        for (uint256 i = 0; i < cats.length; i++) {
            uint256 catId = cats[i];
            address[] storage list = validatorsByCategory[catId];

            for (uint256 j = 0; j < list.length; j++) {
                if (list[j] == msg.sender) {
                    list[j] = list[list.length - 1];
                    list.pop();
                    break;
                }
            }
        }

        delete validatorCategories[msg.sender];
        delete validators[msg.sender];
    }

    function getValidatorsByCategory(uint256 categoryId)
        public
        view
        returns (address[] memory)
    {
        return validatorsByCategory[categoryId];
    }

    // ======================================
    // VALIDACIONES
    // ======================================

    function addValidation(
        uint256 postId,
        uint256 asertionIndex,
        evaluation veredict,
        Multihash memory document
    ) public {
        require(validators[msg.sender].exists, "Not validator");

        Post storage p = postsById[postId];
        require(asertionIndex < p.asertions.length, "Invalid asertion");

        Asertion storage a = p.asertions[asertionIndex];
        uint256 idx = a.validationIndex[msg.sender];

        if (idx == 0) {
            a.validations.push(
                Validation({
                    validator: msg.sender,
                    veredict: veredict,
                    document: document
                })
            );
            a.validationIndex[msg.sender] = a.validations.length;
        } else {
            Validation storage v = a.validations[idx - 1];
            v.veredict = veredict;
            v.document = document;
        }

        // 🔔 Evento de validación registrada (nueva o actualizada)
        emit ValidationSubmitted(
            postId,
            p.document,
            asertionIndex,
            msg.sender,
            document
        );
    }
}
