// contracts/Test.sol
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";

contract TrustManager{

    TrustNew tnContract;
    address public owner;
    
    struct Category{
        string name;
        string description;
    }

    struct Validator{
        address validatorAddress;
        string name;
        uint256 reputation;
    }


    struct Validation{
        Validator validator;
        bool veredict;  
        string description;
    }

    struct Asertion{
        string asertion;
        Validation[] validations;
    }

    struct IPFS_hash {
        bytes1 hash_function;
        bytes1 hash_size;
        bytes32 digest;
    }

    struct Post{
        mapping (string => Asertion) asertions;
        IPFS_hash document;
        address publisher;
        uint256 tokenId;
    }

 

    //Declarem una variable global en forma de  mapping entre el hash de la noticia  i l'estructura de dades. 
    mapping (bytes32 => Post) public  posts;
    mapping (uint256 => Post) public  postsToken;
    mapping (address => Validator) public  validators;
    mapping (string => Validator[]) public  validatorsByCategory;
    

    constructor(TrustNew tokenContract) {
        owner = msg.sender; 
        
        tnContract = tokenContract;
    } 

    function publishNew(string memory text) public returns (uint256 tokenId) {

        bytes1 hash_function;
        bytes1 hash_size;
        bytes32 digest;

        //(hash_function, hash_size, digest) = publishText(text);
        Asertion[] memory asertions;

        //Llamada a API de generateAsertions. asertions = generateAsertions(text);

        //Llamada a API de subudida de documento ipfs
        
        return _publishNew(hash_function, hash_size, digest, asertions, msg.sender);
        
    }


    function _publishNew(bytes1 hash_function, bytes1 hash_size, bytes32 digest, Asertion[] memory asertions,address publisher) private returns (uint256 tokenId) {
        //Devolver error si ya existe un post con el mismo digest
        require(posts[digest].document.digest == 0, "Post already exists");

        Post storage post = posts[digest];
        post.document.hash_function = hash_function;
        post.document.hash_size = hash_size;

        post.publisher = msg.sender; 

        for (uint i = 0; i < asertions.length; i++) {
            post.asertions[asertions[i].asertion] = asertions[i];
        }

        post.tokenId = tnContract.createToken(publisher);


        Post storage postToken = postsToken[post.tokenId];
        postToken.document = post.document;
        postToken.publisher = post.publisher;
        postToken.tokenId = post.tokenId;
        // The asertions mapping is not copied; you may need to access it via posts[digest]

        return post.tokenId;
    }

    function _getText(bytes32 digest) private view returns (
        bytes1 hash_function,
        bytes1 hash_size,
        bytes32 doc_digest,
        address publisher,
        uint256 tokenId
    ) {
        Post storage post = posts[digest];
        return (
            post.document.hash_function,
            post.document.hash_size,
            post.document.digest,
            post.publisher,
            post.tokenId
        );
    }

    function getText(uint256 tokenId) public view returns (
        bytes1 hash_function,
        bytes1 hash_size,
        bytes32 doc_digest,
        address publisher,
        uint256 tokenIdOut
    ) {
        Post storage post = postsToken[tokenId];
        return (
            post.document.hash_function,
            post.document.hash_size,
            post.document.digest,
            post.publisher,
            post.tokenId
        );
    }

    /*function getToken(uint256 tokenId) public view returns (Post storage) {
        Post storage post = postsToken[tokenId];
        return post;
   
    }*/


    function registerValidator(string memory name, string[] memory categories) public {
        require(bytes(name).length != 0, "Invalid name");
        require(categories.length != 0, "Invalid categories");
        //valida que las categorias existan dentro de validatorsByCategory        
        for (uint i = 0; i < categories.length; i++) {
            require(validatorsByCategory[categories[i]].length != 0, "Category not registered");
        }

        validators[msg.sender] = Validator(msg.sender, name, 0);

        for (uint i = 0; i < categories.length; i++) {
            validatorsByCategory[categories[i]].push(validators[msg.sender]);
        }
    }

    function addValidationValidatorRegistered(bytes32 digest, string memory asertion,  bool veredict,string memory description) public {
        // El sender es el validador. Requerir que esté registrado para incluirlo como oficial. 
        // Si ya ha validado actualizar la validacion si es diferente. Si no devolver error

        require(bytes(validators[msg.sender].name).length != 0, "Validator not registered");
    
        posts[digest].asertions[asertion].validations.push(Validation(validators[msg.sender], veredict,description));
    }

}

contract TrustNew is ERC721, ERC721URIStorage {
    
    uint256 private _currentTokenId = 0;

    /*modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }*/

    constructor() ERC721("TrustNews", "TNW") {
    }


    function supportsInterface(bytes4 interfaceId) public view virtual override(ERC721,ERC721URIStorage) returns (bool) {
        return super.supportsInterface(interfaceId);
    }

    function tokenURI(uint256 tokenId) public view virtual override(ERC721,ERC721URIStorage) returns (string memory) {
        return super.tokenURI(tokenId);
    }

    function createToken(address to) public returns (uint256) {
        _currentTokenId += 1;  
        super._safeMint(to, _currentTokenId, "");
        return _currentTokenId;
    }

    function _baseURI()
        internal
        view
        virtual
        override(ERC721)
        returns (string memory)
    {
        return "http:/www.trustnew.org/token/";
    }
}
