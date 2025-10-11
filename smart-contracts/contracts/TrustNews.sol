// contracts/Test.sol
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TrustManager {

    address public owner;
    uint256 public postCounter;
    mapping(uint256 => Post) public postsById;

    struct Category {
        bytes1 id;
        string description;
    }

    struct Validator {
        address validatorAddress;
        string domain;
        uint256 reputation;
    }

    struct Validation {
        bytes1 id;
        Validator validator;
        bool veredict;  
        Multihash hash_description; 
    }

    struct Asertion {
        Multihash hash_asertion;
        Validation[] validations;
    }

    struct Multihash {
        bytes1 hash_function;
        bytes1 hash_size;
        bytes32 digest;
    }

    struct Post {
        // mapping (Multihash => Asertion) asertions; // No permitido como key
        Asertion[] asertions; // Alternativa usando array
        Multihash document; // CID de IPFS
        address publisher;
        Multihash hashNew; // hash para buscar post por texto
    }

    mapping (bytes32 => uint256) public postsHash; // digest de hashNew -> postId
    mapping (bytes32 => uint256) public postsCid;  // digest de document -> postId
    mapping (address => Validator) public validators;
    mapping (bytes1 => Validator[]) public validatorsByCategory;

    constructor() {
        owner = msg.sender;
    } 

    // ======================================
    // FUNCIONES
    // ======================================

    function publishNew(
        Multihash memory hash_new, 
        Multihash memory hash_ipfs, 
        Asertion[] memory asertions
    ) private returns (uint256 PostId) {
        postCounter++;
        Post storage newPost = postsById[postCounter];

        newPost.document = hash_ipfs;
        newPost.hashNew = hash_new;
        newPost.publisher = msg.sender;

        // Copiar asertions de memory a storage
        for (uint i = 0; i < asertions.length; i++) {
            Asertion storage a = newPost.asertions.push();
            a.hash_asertion = asertions[i].hash_asertion;

            for (uint j = 0; j < asertions[i].validations.length; j++) {
                a.validations.push(asertions[i].validations[j]);
            }
        }

        // Registrar los posts por digest para búsqueda
        postsHash[hash_new.digest] = postCounter;
        postsCid[hash_ipfs.digest] = postCounter;

        return postCounter;
    }

    function getNewByHash(Multihash memory hash_new) public view returns (
        Multihash memory hash_cid,
        uint256 PostId
    ) {
        PostId = postsHash[hash_new.digest];
        hash_cid = postsById[PostId].document;
    }

    function getNewByCid(Multihash memory hash_cid) public view returns (
        Multihash memory hash_new,
        uint256 PostId
    ) {
        PostId = postsCid[hash_cid.digest];
        hash_new = postsById[PostId].hashNew;
    }

    function getValidationsByNew(uint256 PostId) public view returns (Validation[] memory) {
        // Por ahora devolvemos las validaciones de todas las asertions concatenadas
        uint totalValidations = 0;
        Post storage p = postsById[PostId];
        for (uint i = 0; i < p.asertions.length; i++) {
            totalValidations += p.asertions[i].validations.length;
        }

        Validation[] memory allValidations = new Validation[](totalValidations);
        uint k = 0;
        for (uint i = 0; i < p.asertions.length; i++) {
            for (uint j = 0; j < p.asertions[i].validations.length; j++) {
                allValidations[k] = p.asertions[i].validations[j];
                k++;
            }
        }
        return allValidations;
    }

    function registerValidator(string memory name, string[] memory categories) public {
        require(bytes(name).length != 0, "Invalid name");
        require(categories.length != 0, "Invalid categories");
        // valida que las categorias existan dentro de validatorsByCategory
        for (uint i = 0; i < categories.length; i++) {
            require(validatorsByCategory[bytes1(bytes(categories[i])[0])].length != 0, "Category not registered");
        }

        validators[msg.sender] = Validator(msg.sender, name, 0);

        for (uint i = 0; i < categories.length; i++) {
            validatorsByCategory[bytes1(bytes(categories[i])[0])].push(validators[msg.sender]);
        }
    }

    function addValidation(
        uint256 PostId,
        uint256 asertionIndex,
        bool veredict,
        Multihash memory hash_description
    ) public {
        // El sender es el validador. Requerir que esté registrado
        require(validators[msg.sender].validatorAddress != address(0), "Validator not registered");

        Post storage p = postsById[PostId];
        require(asertionIndex < p.asertions.length, "Invalid asertion index");

        Validation memory v = Validation({
            id: bytes1(0), // Puedes generar un id aquí
            validator: validators[msg.sender],
            veredict: veredict,
            hash_description: hash_description
        });

        // Añadir o actualizar validación
        p.asertions[asertionIndex].validations.push(v);
    }
}
