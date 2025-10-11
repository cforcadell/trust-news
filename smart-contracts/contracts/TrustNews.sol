// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TrustNews {

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
        Asertion[] asertions;
        Multihash document; 
        address publisher;
        Multihash hashNew; 
    }

    mapping (bytes32 => uint256) public postsHash;
    mapping (bytes32 => uint256) public postsCid;
    mapping (address => Validator) public validators;
    mapping (bytes1 => Validator[]) public validatorsByCategory;
    mapping (bytes1 => string) public categories; // 🔹 Nueva estructura

    constructor() {
        owner = msg.sender;
    } 

    // ======================================
    // PUBLICACIONES
    // ======================================

    function publishNew(
        Multihash memory hash_new, 
        Multihash memory hash_ipfs, 
        Asertion[] memory asertions
    ) public returns (uint256 PostId, bytes1[] memory asertionIds, address[] memory validatorAddresses) {
        postCounter++;
        Post storage newPost = postsById[postCounter];

        newPost.document = hash_ipfs;
        newPost.hashNew = hash_new;
        newPost.publisher = msg.sender;

        uint totalValidations = 0;
        for (uint i = 0; i < asertions.length; i++) {
            totalValidations += asertions[i].validations.length;
        }

        asertionIds = new bytes1[](totalValidations);
        validatorAddresses = new address[](totalValidations);

        uint idx = 0;
        for (uint i = 0; i < asertions.length; i++) {
            Asertion storage a = newPost.asertions.push();
            a.hash_asertion = asertions[i].hash_asertion;

            for (uint j = 0; j < asertions[i].validations.length; j++) {
                a.validations.push(asertions[i].validations[j]);
                asertionIds[idx] = asertions[i].validations[j].id;
                validatorAddresses[idx] = asertions[i].validations[j].validator.validatorAddress;
                idx++;
            }
        }

        postsHash[hash_new.digest] = postCounter;
        postsCid[hash_ipfs.digest] = postCounter;

        return (postCounter, asertionIds, validatorAddresses);
    }

    // ======================================
    // CONSULTAS
    // ======================================

    function getNewByHash(Multihash memory hash_new) public view returns (Multihash memory hash_cid, uint256 PostId) {
        PostId = postsHash[hash_new.digest];
        hash_cid = postsById[PostId].document;
    }

    function getNewByCid(Multihash memory hash_cid) public view returns (Multihash memory hash_new, uint256 PostId) {
        PostId = postsCid[hash_cid.digest];
        hash_new = postsById[PostId].hashNew;
    }

    function getValidationsByNew(uint256 PostId) public view returns (Validation[] memory) {
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

    // ======================================
    // VALIDADORES Y CATEGORÍAS
    // ======================================

    function addCategory(bytes1 id, string memory description) public {
        require(msg.sender == owner, "Only owner can add categories");
        require(bytes(categories[id]).length == 0, "Category already exists");
        categories[id] = description;
    }

    function registerValidator(string memory name, string[] memory categoryIds) public {
        require(bytes(name).length != 0, "Invalid name");
        require(categoryIds.length != 0, "Invalid categories");

        for (uint i = 0; i < categoryIds.length; i++) {
            bytes1 catId = bytes1(bytes(categoryIds[i])[0]);
            require(bytes(categories[catId]).length != 0, "Category not registered");
        }

        validators[msg.sender] = Validator(msg.sender, name, 0);

        for (uint i = 0; i < categoryIds.length; i++) {
            bytes1 catId = bytes1(bytes(categoryIds[i])[0]);
            validatorsByCategory[catId].push(validators[msg.sender]);
        }
    }

    function addValidation(
        uint256 PostId,
        uint256 asertionIndex,
        bool veredict,
        Multihash memory hash_description
    ) public {
        require(validators[msg.sender].validatorAddress != address(0), "Validator not registered");

        Post storage p = postsById[PostId];
        require(asertionIndex < p.asertions.length, "Invalid asertion index");

        Validation memory v = Validation({
            id: bytes1(0),
            validator: validators[msg.sender],
            veredict: veredict,
            hash_description: hash_description
        });

        p.asertions[asertionIndex].validations.push(v);
    }
}
