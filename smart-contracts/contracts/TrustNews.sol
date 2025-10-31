// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

contract TrustNews {

    address public owner;
    uint256 public postCounter;
    mapping(uint256 => Post) public postsById;

    struct Category {
        uint256 id;
        string description;
    }

    struct Validator {
        address validatorAddress;
        string domain;
        uint256 reputation;
    }

    struct Validation {
        Validator validator;
        bool veredict;  
        Multihash hash_description; 
    }

    struct Asertion {
        Multihash hash_asertion;
        Validation[] validations;
        uint256 categoryId;
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

    struct ValidationView {
        address validatorAddress;
        string domain;
        uint256 reputation;
        bool veredict;
        Multihash hash_description;
    }

    struct AsertionView {
        Multihash hash_asertion;
        ValidationView[] validations;
        uint256 categoryId;   
    }

    mapping (bytes32 => uint256) public postsHash;
    mapping (bytes32 => uint256) public postsCid;
    mapping (address => Validator) public validators;
    mapping (uint256 => Validator[]) public validatorsByCategory;
    mapping (uint256 => string) public categories; 

    event RegisterNewResult(uint256  postId,Multihash hashNews,address[][] validatorAddressesByAsertion);


    constructor() {
        owner = msg.sender;
    } 

    // ======================================
    // PUBLICACIONES
    // ======================================

function registerNew(
    Multihash memory hash_new,
    Multihash memory hash_ipfs,
    Asertion[] memory asertions,
    uint256[] memory categoryIds
)
    public
    returns (
        uint256 postId,
        address[][] memory validatorAddressesByAsertion
    )
{
    require(asertions.length == categoryIds.length, "Cada asercion debe tener su categoria");

    postCounter++;
    postId = postCounter;
    Post storage newPost = postsById[postCounter];
    newPost.document = hash_ipfs;
    newPost.hashNew = hash_new;
    newPost.publisher = msg.sender;

    uint256 numAsertions = asertions.length;
    validatorAddressesByAsertion = new address[][](numAsertions);

    for (uint256 i = 0; i < numAsertions; i++) {
        uint256 categoryId = categoryIds[i];
        Validator[] storage catValidators = validatorsByCategory[categoryId];
        uint256 numValidators = catValidators.length;

        // Añadimos la aserción con categoryId
        Asertion storage a = newPost.asertions.push();
        a.hash_asertion = asertions[i].hash_asertion;
        a.categoryId = categoryId;  // ← nueva línea

        // Creamos el array de direcciones para esta aserción
        validatorAddressesByAsertion[i] = new address[](numValidators);

        for (uint256 j = 0; j < numValidators; j++) {
            validatorAddressesByAsertion[i][j] = catValidators[j].validatorAddress;
        }
    }

    postsHash[hash_new.digest] = postCounter;
    postsCid[hash_ipfs.digest] = postCounter;


    emit RegisterNewResult(postId, hash_new, validatorAddressesByAsertion);
    return (postId, validatorAddressesByAsertion);
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

    function getAsertionsWithValidations(uint256 postId)
        public
        view
        returns (AsertionView[] memory)
    {
        Post storage p = postsById[postId];
        uint256 numAsertions = p.asertions.length;

        // Array de salida
        AsertionView[] memory asertionViews = new AsertionView[](numAsertions);

        // Iterar sobre todas las aserciones
        for (uint256 i = 0; i < numAsertions; i++) {
            Asertion storage a = p.asertions[i];
            uint256 numValidations = a.validations.length;

            // Copiar hash_asertion
            asertionViews[i].hash_asertion = a.hash_asertion;
            asertionViews[i].categoryId = a.categoryId;

            // Crear array temporal de validaciones
            ValidationView[] memory validationViews = new ValidationView[](numValidations);

            // Copiar las validaciones y los datos del validador
            for (uint256 j = 0; j < numValidations; j++) {
                Validation storage v = a.validations[j];
                validationViews[j] = ValidationView({
                    validatorAddress: v.validator.validatorAddress,
                    domain: v.validator.domain,
                    reputation: v.validator.reputation,
                    veredict: v.veredict,
                    hash_description: v.hash_description
                });
            }

            // Asignar al resultado
            asertionViews[i].validations = validationViews;
        }

        return asertionViews;
    }


    // ======================================
    // VALIDADORES Y CATEGORÍAS
    // ======================================

    function addCategory(uint256 id, string memory description) public {
        require(msg.sender == owner, "Only owner can add categories");
        require(bytes(categories[id]).length == 0, "Category already exists");
        categories[id] = description;
    }

    function registerValidator(string memory name, uint256[] memory categoryIds) public {
        require(bytes(name).length != 0, "Invalid name");
        require(categoryIds.length != 0, "Invalid categories");

        for (uint i = 0; i < categoryIds.length; i++) {
            uint256 catId = categoryIds[i];
            require(bytes(categories[catId]).length != 0, "Category not registered");
        }

        validators[msg.sender] = Validator(msg.sender, name, 0);

        for (uint i = 0; i < categoryIds.length; i++) {
            uint256 catId = categoryIds[i];
            validatorsByCategory[catId].push(validators[msg.sender]);
        }
    }


    function getValidatorsByCategory(uint256 categoryId) public view returns (address[] memory) {
        Validator[] storage catValidators = validatorsByCategory[categoryId];
        uint256 numValidators = catValidators.length;
        address[] memory validatorAddresses = new address[](numValidators);

        for (uint256 i = 0; i < numValidators; i++) {
            validatorAddresses[i] = catValidators[i].validatorAddress;
        }

        return validatorAddresses;
    }

    function addValidation(
        uint256 postId,
        uint256 asertionIndex,
        bool veredict,
        Multihash memory hash_description
    ) public {
        // Asegurar que el validador está registrado
        require(
            validators[msg.sender].validatorAddress != address(0),
            "Validator not registered"
        );

        // Recuperar el post y verificar índices válidos
        Post storage p = postsById[postId];
        require(asertionIndex < p.asertions.length, "Invalid asertion index");

        // Buscar si el validador ya emitió una validación
        Validation[] storage validations = p.asertions[asertionIndex].validations;
        bool updated = false;

        for (uint256 i = 0; i < validations.length; i++) {
            if (validations[i].validator.validatorAddress == msg.sender) {
                //Actualizar validación existente
                validations[i].veredict = veredict;
                validations[i].hash_description = hash_description;
                updated = true;
                break;
            }
        }

        // Si no existe, añadir nueva validación
        if (!updated) {
            Validation memory v = Validation({
                validator: validators[msg.sender],
                veredict: veredict,
                hash_description: hash_description
            });
            validations.push(v);
        }
    }

}