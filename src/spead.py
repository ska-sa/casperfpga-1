"""
SPEAD operations - unpack and use spead data, usually from Snap blocks.
"""
import logging

LOGGER = logging.getLogger(__name__)


def decode_spead_magic_word(word64, required_version=None, required_flavour=None, required_numheaders=None):
    """
    Decode a 64-bit word as a SPEAD header.
    :param word64: A 64-bit word
    :param required_version: the specific SPEAD version required, an integer
    :param required_flavour:  the specific SPEAD flavour required as a string, e.g. '64,48'
    :param required_numheaders: the number of headers (NOT incl. the magic number) expected, an integer
    :return:
    """
    magic_number = word64 >> 56
    spead_version = (word64 >> 48) & 0xff
    spead_id_width = (word64 >> 40) & 0xff
    spead_addr_width = (word64 >> 32) & 0xff
    reserved = (word64 >> 16) & 0xffff
    num_headers = word64 & 0xffff
    spead_flavour = '%s,%s' % ((spead_addr_width * 8) + (spead_id_width * 8), (spead_addr_width * 8))
    assert magic_number == 83, 'Wrong SPEAD magic number: %i != 83' % magic_number
    assert reserved == 0, 'SPEAD reserved not zero: %i != 0' % reserved
    if required_version is not None:
        assert spead_version == required_version, 'Wrong SPEAD version: %i != %i' % \
                                                  (spead_version, required_version)
    if required_flavour is not None:
        assert spead_flavour == required_flavour, 'Wrong SPEAD flavour: %s != %s' % \
                                                  (spead_flavour, required_flavour)
    if required_numheaders is not None:
        assert num_headers == required_numheaders, 'Wrong num SPEAD hdrs: %i != %i' % \
                                                   (num_headers, required_numheaders)
    return {'magic_number': magic_number,
            'version': spead_version,
            'id_bits': spead_id_width * 8,
            'address_bits': spead_addr_width * 8,
            'reserved': reserved,
            'num_headers': num_headers,
            'flavour': spead_flavour}


def find_spead_header(data64, expected_version=4, expected_flavour='64,48'):
    """
    Find a SPEAD header in the given list of 64-bit data
    :param data64: a list of data
    :param expected_version: the version wanted
    :param expected_flavour: the flavour wanted
    :return: None if no header is found, else the index and the contents of the header as a tuple
    """
    for __ctr, dataword in enumerate(data64):
        decoded = decode_spead_magic_word(dataword)
        if (decoded['version'] == expected_version) and (decoded['flavour'] == expected_flavour):
            return __ctr, decoded
    return None


def decode_item_pointer(header64, id_bits, address_bits):
    """
    Decode a 64-bit header word in the id and data/pointer portions
    :param header64: the 64-bit word
    :param id_bits: how many bits are used for the ID
    :param address_bits: how many bits are used for the data/pointer
    :return: a tuple of the ID and data/pointer
    """
    hdr_id = header64 >> address_bits
    # if the top bit is set, it's immediate addressing so clear the top bit
    if hdr_id & pow(2, id_bits - 1):
        hdr_id &= pow(2, id_bits - 1) - 1
    hdr_data = header64 & (pow(2, address_bits) - 1)
    return hdr_id, hdr_data


class SpeadPacket(object):
    """
    A Spead Packet. Headers and data.
    """
    def __init__(self, headers=None, data=None):
        self.headers = headers if headers is not None else {}
        self.data = data if data is not None else []

    @classmethod
    def from_data(cls, data, expected_version=None, expected_flavour=None, expected_hdrs=None, expected_length=None):
        """
        Create a SpeadPacket from a list of 64-bit data words
        """
        main_header = decode_spead_magic_word(data[0], required_version=expected_version,
                                              required_flavour=expected_flavour,
                                              required_numheaders=expected_hdrs)
        headers = {0x0000: main_header}
        packet_length = -1
        for ctr in range(1, main_header['num_headers']+1):
            hdr_id, hdr_data = decode_item_pointer(data[ctr], main_header['id_bits'], main_header['address_bits'])
            if hdr_id in headers.keys():
                print headers
                raise RuntimeError('Header ID 0x%04x already in packet headers.' % hdr_id)
            headers[hdr_id] = hdr_data
            if hdr_id == 0x0004:
                packet_length = hdr_data
        if expected_hdrs is not None:
            if len(headers) != expected_hdrs + 1:
                raise RuntimeError('Packet does not the correct number of headers: %i != %i' %
                                   (len(headers), expected_hdrs + 1))
        pktdata = []
        pktlen = 0
        for ctr in range(main_header['num_headers']+1, len(data)):
            pktdata.append(data[ctr])
            pktlen += 1
        if pktlen != expected_length:
            raise RuntimeError('Packet is not the expected length: %i != %i' % (pktlen, expected_length))
        if pktlen*8 != packet_length:
            raise RuntimeError('Packet is not the same length as indicated in the SPEAD header: %i != %i' %
                               (pktlen*8, packet_length))
        obj = cls(headers, pktdata)
        return obj

    def get_strings(self, headers_only=False, hex_nums=False):
        """
        Get a list of the string representation of this packet.
        """
        rv = []
        for hdr_id, hdr_value in self.headers.items():
            if hdr_id == 0x0000:
                rv.append('header 0x0000: version(%i) flavour(%s) num_headers(%i)' % (
                    self.headers[0]['version'],
                    self.headers[0]['flavour'],
                    self.headers[0]['num_headers'],))
            else:
                if hex_nums:
                    rv.append('header 0x%04x: 0x%x' % (hdr_id, hdr_value))
                else:
                    rv.append('header 0x%04x: %i' % (hdr_id, hdr_value))
        if headers_only:
            return rv
        for dataword in self.data:
            rv.append('%i' % dataword)
        return rv

    def print_packet(self, headers_only=False, hex_nums=False):
        """
        Print a representation of the packet.
        """
        for string in self.get_strings(headers_only, hex_nums):
            print string


class SpeadProcessor(object):
    """
    Set up a SPEAD processor with version, flavour, etc. Then call methods to process data.
    """
    def __init__(self, version, flavour, packet_length=None, num_headers=None):
        """
        Create a SpeadProcessor
        """
        self.packets = []
        self.version = version
        self.flavour = flavour
        self.expected_num_headers = num_headers
        self.expected_packet_length = packet_length

    def process_data(self, data_packets):
        """
        Create SpeadPacket objects from a list of data packets.
        """
        for pkt in data_packets:
            spead_pkt = SpeadPacket.from_data(pkt, self.version, self.flavour, self.expected_num_headers,
                                              self.expected_packet_length)
            self.packets.append(spead_pkt)


# def process_spead_word(current_spead_info, data, pkt_counter):
#
#     if pkt_counter == 1:
#         spead_header = decode_spead_magic_word(data)
#         if len(current_spead_info) == 0:
#             current_spead_info = spead_header
#         rv_string = 'spead %s, %d headers to come' % (spead_header['flavour'], spead_header['num_headers'])
#         if current_spead_info['num_headers'] != spead_header['num_headers']:
#             rv_string += ', ERROR: num spead hdrs changed from %d to %d?!' %\
#                          (current_spead_info['num_headers'], spead_header['num_headers'])
#         return spead_header, rv_string
#     elif (pkt_counter > 1) and (pkt_counter <= 1 + current_spead_info['num_headers']):
#         hdr_id, hdr_data = decode_item_pointer(data, current_spead_info['id_bits'], current_spead_info['address_bits'])
#         if hdr_id == 0x0004:
#             # the SPEAD packet length is in BYTES! we're counting 64-bit words, so divide by 8
#             current_spead_info['packet_length'] = current_spead_info['num_headers'] + (hdr_data / 8)
#         string_data = 'spead hdr 0x%04x: ' % hdr_id + ('%d' % hdr_data if not True else '0x%X' % hdr_data)
#         return current_spead_info if hdr_id == 0x0004 else None, string_data
#     else:
#         # data = '%d, %d, %d, %d' % (data >> 48, (data >> 32) & 0xffff, (data >> 16) & 0xffff, (data >> 0) & 0xffff)
#         return None, data


# def gbe_to_spead(gbedata):
#     pkt_counter = 1
#     _current_packet = {'headers': {}, 'data': []}
#     for wordctr in range(0, len(gbedata)):
#         if pkt_counter == 1:
#             spead_header = decode_spead_magic_word(gbedata[wordctr])
#             _current_packet['headers'][0] = spead_header
#         elif (pkt_counter > 1) and (pkt_counter <= 1 + _current_packet['headers'][0]['num_headers']):
#             hdr_id, hdr_data = decode_item_pointer(gbedata[wordctr],
#                                                    _current_packet['headers'][0]['id_bits'],
#                                                    _current_packet['headers'][0]['address_bits'])
#             # the SPEAD packet length is in BYTES! we're counting 64-bit words, so divide by 8
#             if hdr_id == 0x0004:
#                 _current_packet['headers'][0]['packet_length'] = _current_packet['headers'][0]['num_headers'] + \
#                                                                  (hdr_data / 8)
#             if hdr_id in _current_packet['headers'].keys():
#                 raise RuntimeError('Header ID 0x%04x already exists in packet!' % hdr_id)
#             _current_packet['headers'][hdr_id] = hdr_data
#         else:
#             _current_packet['data'].append(gbedata[wordctr])
#         pkt_counter += 1
#     if _current_packet['headers'][0]['packet_length'] + 1 != len(gbedata):
#         raise ValueError('SPEAD header packet length %d does not match GBE packet length %d') % \
#               (_current_packet['headers'][0]['packet_length'] + 1, len(gbedata))
#     return _current_packet


# def decode_spead(spead_data, eof_data=None):
#     """
#     Given a data list and EOF list from a snapblock, decode SPEAD data and store it in spead packets
#     """
#     if eof_data is not None:
#         if len(spead_data) != len(eof_data):
#             raise RuntimeError('Need EOF and data lengths to be the same!')
#         first_spead_header = find_spead_header(spead_data, SPEAD_EXPECTED_VERSION, SPEAD_EXPECTED_FLAVOUR)
#         if first_spead_header == -1:
#             raise RuntimeError('Could not find valid SPEAD header.')
#     else:
#         first_spead_header = 0
#     spead_packets = []
#     _current_packet = {'headers': {}, 'data': []}
#     pkt_counter = 1
#     for wordctr in range(first_spead_header, len(spead_data)):
#         if eof_data[wordctr]:
#             if pkt_counter != _current_packet['headers'][0]['packet_length'] + 1:
#                 _current_packet['headers'][0]['length_error'] = True
#             spead_packets.append(_current_packet)
#             _current_packet = {'headers': {}, 'data': []}
#             pkt_counter = 0
#         elif pkt_counter == 1:
#             spead_header = decode_spead_header(spead_data[wordctr])
#             if len(spead_packets) > 0:
#                 if spead_packets[0]['headers'][0]['num_headers'] != spead_header['num_headers']:
#                     raise RuntimeError('SPEAD header format changed mid-snapshot?')
#             _current_packet['headers'][0] = spead_header
#         elif (pkt_counter > 1) and (pkt_counter <= 1 + _current_packet['headers'][0]['num_headers']):
#             hdr_id, hdr_data = decode_item_pointer_(_current_packet['headers'][0]['address_bits'],
#                                                     _current_packet['headers'][0]['id_bits'],
#                                                     spead_data[wordctr])
#             # the SPEAD packet length is in BYTES! we're counting 64-bit words, so divide by 8
#             if hdr_id == 0x0004:
#                 _current_packet['headers'][0]['packet_length'] = _current_packet['headers'][0]['num_headers'] + \
#                                                                  (hdr_data / 8)
#             if hdr_id in _current_packet['headers'].keys():
#                 raise RuntimeError('Header ID 0x%04x already exists in packet!' % hdr_id)
#             _current_packet['headers'][hdr_id] = hdr_data
#         else:
#             _current_packet['data'].append(spead_data[wordctr])
#         pkt_counter += 1
#     return spead_packets
