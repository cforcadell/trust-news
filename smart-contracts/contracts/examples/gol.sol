// SPDX-License-Identifier: MIT
pragma solidity ^0.8.18;

// Libraries
//import "../deps/npm/@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/token/ERC721/ERC721.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721URIStorage.sol";
import "@openzeppelin/contracts/token/ERC721/extensions/ERC721Burnable.sol";

contract gol is ERC721, ERC721URIStorage, ERC721Burnable{ 

    address public owner;

    constructor() ERC721("Gol", "G") {

        owner = msg.sender; 
    }

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    function supportsInterface(bytes4 interfaceId) public view virtual override(ERC721,ERC721URIStorage) returns (bool) {
        return super.supportsInterface(interfaceId);
    }

    function tokenURI(uint256 tokenId) public view virtual override(ERC721,ERC721URIStorage) returns (string memory) {
        return super.tokenURI(tokenId);
    }

    function encunya(address to, uint256 tokenId) public onlyOwner{
        super._safeMint(to, tokenId, "");
    }

    function _baseURI() internal view virtual override(ERC721)  returns  (string memory) {
        return "http:/www.bestgoalsever.com/token/";
    }
}