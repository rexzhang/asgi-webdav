from typing import Callable
from logging import getLogger

import xmltodict

from asgi_webdav.constants import (
    DAV_METHODS,
    DAVPath,
    DAVLockInfo,
    DAVPassport,
    DAVPropertyIdentity,
    DAVPropertyPatches,
    DAVProperty,
    DAVResponse,
)
from asgi_webdav.helpers import (
    receive_all_data_in_one_call,
)
from asgi_webdav.request import DAVRequest
from asgi_webdav.lock import DAVLock

logger = getLogger(__name__)


class DAVProvider:
    def __init__(self):
        self.lock = DAVLock()

    @staticmethod
    def _create_ns_key_with_id(
        ns_map: dict[str, str], ns: str, key: str
    ) -> str:
        if len(ns) == 0:
            # no namespace
            return key

        ns_id = ns_map.setdefault(ns, 'ns{}'.format(len(ns_map) + 1))
        return '{}:{}'.format(ns_id, key)

    @staticmethod
    def _create_data_lock_discovery(lock_info: DAVLockInfo) -> dict:
        if lock_info.depth == -1:
            depth = 'infinity'
        else:
            depth = lock_info.depth

        return {
            'D:activelock': {
                'D:locktype': {
                    'D:write': None
                },
                'D:lockscope': {
                    'D:{}'.format(lock_info.scope.name): None
                },
                'D:depth': depth,
                'D:owner': lock_info.owner,
                'D:timeout': 'Second-{}'.format(lock_info.timeout),
                'D:locktoken': {
                    'D:href': 'opaquelocktoken:{}'.format(lock_info.token),
                },
            },
        }

    """
    https://tools.ietf.org/html/rfc4918#page-35
    9.1.1.  PROPFIND Status Codes
    
       This section, as with similar sections for other methods, provides
       some guidance on error codes and preconditions or postconditions
       (defined in Section 16) that might be particularly useful with
       PROPFIND.
    
       403 Forbidden - A server MAY reject PROPFIND requests on collections
       with depth header of "Infinity", in which case it SHOULD use this
       error with the precondition code 'propfind-finite-depth' inside the
       error body.
    
    9.1.2.  Status Codes for Use in 'propstat' Element
    
       In PROPFIND responses, information about individual properties_list is
       returned inside 'propstat' elements (see Section 14.22), each
       containing an individual 'status' element containing information
       about the properties_list appearing in it.  The list below summarizes the
       most common status codes used inside 'propstat'; however, clients
       should be prepared to handle other 2/3/4/5xx series status codes as
       well.
    
       200 OK - A property exists and/or its value is successfully returned.
    
       401 Unauthorized - The property cannot be viewed without appropriate
       authorization.
    
       403 Forbidden - The property cannot be viewed regardless of
       authentication.
    
       404 Not Found - The property does not exist.
    
    https://tools.ietf.org/html/rfc4918#page-78
    11.1.  207 Multi-Status
    
       The 207 (Multi-Status) status code provides status for multiple
       independent operations (see Section 13 for more information).    
    """

    async def do_propfind(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:
        if not request.body_is_parsed_success:
            # TODO ??? 40x?
            await DAVResponse(400).send_in_one_call(request.send)
            return False

        properties = await self._do_propfind(request, passport)
        if properties is None:
            await DAVResponse(404).send_in_one_call(request.send)
            return False

        data = await self._create_propfind_response(properties, passport)
        response = DAVResponse(status=207, message=data, headers=[
            (b'Content-Length', bytes(str(len(data)), encoding='utf-8')),
        ])
        await response.send_in_one_call(request.send)
        return True

    async def _do_propfind(
        self, request: DAVRequest, passport: DAVPassport
    ) -> list[DAVProperty]:
        raise NotImplementedError

    async def _create_propfind_response(
        self, properties_list: list[DAVProperty], passport: DAVPassport
    ) -> bytes:
        response = list()
        ns_map = dict()
        for dav_property in properties_list:
            href_path = passport.src_prefix.append_child(dav_property.path.raw)

            found_property = dict()
            # basic data
            for k, v in dav_property.basic_data.items():
                found_property['D:' + k] = v
            if dav_property.is_collection:
                found_property['D:resourcetype'] = {'D:collection': None}
            else:
                found_property['D:resourcetype'] = None

            # extra data
            for (ns, key), value in dav_property.extra_data.items():
                ns_id = self._create_ns_key_with_id(ns_map, ns, key)
                found_property[ns_id] = value

            # lock
            lock_info = await self.lock.get_info_by_path(href_path)
            if len(lock_info) > 0:
                # TODO!!!! multi-token
                lock_discovery = self._create_data_lock_discovery(
                    lock_info[0]
                )
            else:
                lock_discovery = None

            response_item = {
                'D:href': href_path.raw,
                'D:propstat': [{
                    'D:prop': found_property,
                    # 'D:supportedlock': {
                    #     'D:lockentry': [
                    #         {
                    #             'D:lockscope': {'D:exclusive': ''},
                    #             'D:locktype': {'D:write': ''}
                    #         },
                    #         {
                    #             'D:lockscope': {'D:shared': None},
                    #             'D:locktype': {'D:write': None}
                    #         }
                    #     ]
                    # },
                    'D:lockdiscovery': lock_discovery,
                    'D:status': 'HTTP/1.1 200 OK',
                }],
            }

            # extra not found
            if len(dav_property.extra_not_found) > 0:
                not_found_property = dict()
                for ns, key in dav_property.extra_not_found:
                    ns_id = self._create_ns_key_with_id(ns_map, ns, key)
                    not_found_property[ns_id] = None

                not_found_property = {
                    'D:prop': not_found_property,
                    'D:status': 'HTTP/1.1 404 Not Found',
                }
                response_item['D:propstat'].append(not_found_property)

            # namespace
            # TODO ns0 => DAV:
            for k, v in ns_map.items():
                response_item['@xmlns:{}'.format(v)] = k

            # pprint(item)
            response.append(response_item)

        data = {
            'D:multistatus': {
                '@xmlns:D': 'DAV:',
                'D:response': response,
            }
        }
        return xmltodict.unparse(
            data, short_empty_elements=True
        ).replace('\n', '').encode('utf-8')

    """
    https://tools.ietf.org/html/rfc4918#page-44
    9.2.  PROPPATCH Method    
    9.2.1.  Status Codes for Use in 'propstat' Element
    
       In PROPPATCH responses, information about individual properties_list is
       returned inside 'propstat' elements (see Section 14.22), each
       containing an individual 'status' element containing information
       about the properties_list appearing in it.  The list below summarizes the
       most common status codes used inside 'propstat'; however, clients
       should be prepared to handle other 2/3/4/5xx series status codes as
       well.
    
       200 (OK) - The property set or change succeeded.  Note that if this
       appears for one property, it appears for every property in the
       response, due to the atomicity of PROPPATCH.
    
       403 (Forbidden) - The client, for reasons the server chooses not to
       specify, cannot alter one of the properties_list.
    
       403 (Forbidden): The client has attempted to set a protected
       property, such as DAV:getetag.  If returning this error, the server
       SHOULD use the precondition code 'cannot-modify-protected-property'
       inside the response body.
    
       409 (Conflict) - The client has provided a value whose semantics are
       not appropriate for the property.
    
       424 (Failed Dependency) - The property change could not be made
       because of another property change that failed.
    
       507 (Insufficient Storage) - The server did not have sufficient space
       to record the property.   
    """

    async def do_proppatch(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:
        if not request.body_is_parsed_success:
            await DAVResponse(400).send_in_one_call(request.send)
            return False

        http_status = await self._do_proppatch(request, passport)

        if await self.lock.is_locking(request.src_path, request.lock_token):
            await DAVResponse(423).send_in_one_call(request.send)
            return False

        if http_status == 207:
            sucess_ids = [x[0] for x in request.proppatch_entries]
            message = self._create_proppatch_response(
                passport.src_prefix, request.src_path, sucess_ids
            )
        else:
            message = b''

        await DAVResponse(http_status, message).send_in_one_call(request.send)
        return True

    async def _do_proppatch(
        self, request: DAVRequest, passport: DAVPassport
    ) -> int:
        raise NotImplementedError

    @staticmethod
    def _create_proppatch_response(
        prefix, path, sucess_ids: list[DAVPropertyIdentity]
    ) -> bytes:
        data = dict()
        for ns, key in sucess_ids:
            # data['ns1:{}'.format(item)] = None
            data['D:{}'.format(key)] = None  # TODO namespace

        # href = '{}{}'.format(prefix, path)
        data = {
            'D:multistatus': {
                '@xmlns:D': 'DAV:',
                'D:response': {
                    'D:href': path,
                    'D:propstat': {
                        'D:prop': data,
                        'D:status': 'HTTP/1.1 200 OK',
                    }
                },
            }
        }
        return xmltodict.unparse(
            data, short_empty_elements=True
        ).replace('\n', '').encode('utf-8')

    """
    https://tools.ietf.org/html/rfc4918#page-46
    9.3.1.  MKCOL Status Codes
    
       In addition to the general status codes possible, the following
       status codes have specific applicability to MKCOL:
    
       201 (Created) - The collection was created.
    
       403 (Forbidden) - This indicates at least one of two conditions: 1)
       the server does not allow the creation of collections at the given
       location in its URL namespace, or 2) the parent collection of the
       Request-URI exists but cannot accept members.
    
       405 (Method Not Allowed) - MKCOL can only be executed on an unmapped
       URL.
    
       409 (Conflict) - A collection cannot be made at the Request-URI until
       one or more intermediate collections have been created.  The server
       MUST NOT create those intermediate collections automatically.
    
       415 (Unsupported Media Type) - The server does not support the
       request body type (although bodies are legal on MKCOL requests, since
       this specification doesn't define any, the server is likely not to
       support any given body type).
    
       507 (Insufficient Storage) - The resource does not have sufficient
       space to record the state of the resource after the execution of this
       method.
    """

    async def do_mkcol(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:
        request_data = await receive_all_data_in_one_call(request.receive)
        if len(request_data) > 0:
            # https://tools.ietf.org/html/rfc2518#page-33
            # https://tools.ietf.org/html/rfc4918#page-46
            await DAVResponse(415).send_in_one_call(request.send)
            return False

        http_status = await self._do_mkcol(passport.src_path)
        await DAVResponse(http_status).send_in_one_call(request.send)

        return True

    async def _do_mkcol(self, path: DAVPath) -> int:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-48
    9.4.  GET, HEAD for Collections
    
       The semantics of GET are unchanged when applied to a collection,
       since GET is defined as, "retrieve whatever information (in the form
       of an entity) is identified by the Request-URI" [RFC2616].  GET, when
       applied to a collection, may return the contents of an "index.html"
       resource, a human-readable view of the contents of the collection, or
       something else altogether.  Hence, it is possible that the result of
       a GET on a collection will bear no correlation to the membership of
       the collection.
    
       Similarly, since the definition of HEAD is a GET without a response
       message body, the semantics of HEAD are unmodified when applied to
       collection resources.
    
    https://tools.ietf.org/html/rfc2616#page-53
    9.3 GET
    
       The GET method means retrieve whatever information (in the form of an
       entity) is identified by the Request-URI. If the Request-URI refers
       to a data-producing process, it is the produced data which shall be
       returned as the entity in the response and not the source text of the
       process, unless that text happens to be the output of the process.
    
       The semantics of the GET method change to a "conditional GET" if the
       request message includes an If-Modified-Since, If-Unmodified-Since,
       If-Match, If-None-Match, or If-Range header field. A conditional GET
       method requests that the entity be transferred only under the
       circumstances described by the conditional header field(s). The
       conditional GET method is intended to reduce unnecessary network
       usage by allowing cached entities to be refreshed without requiring
       multiple requests or transferring data already held by the client.
    
       The semantics of the GET method change to a "partial GET" if the
       request message includes a Range header field. A partial GET requests
       that only part of the entity be transferred, as described in section
       14.35. The partial GET method is intended to reduce unnecessary
       network usage by allowing partially-retrieved entities to be
       completed without transferring data already held by the client.
    
       The response to a GET request is cacheable if and only if it meets
       the requirements for HTTP caching described in section 13.
    
       See section 15.1.3 for security considerations when used for forms.
    """

    async def do_get(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:
        http_status = await self._do_get(
            request, passport.src_path, request.send
        )
        if http_status != 200:
            # TODO bug
            await DAVResponse(http_status).send_in_one_call(request.send)

        return True

    async def _do_get(
        self, request: DAVRequest, path: DAVPath, send: Callable
    ) -> int:
        raise NotImplementedError

    async def do_head(
        self, request: DAVRequest, passport: DAVPassport
    ):
        if await self._do_head(passport.src_path):
            await DAVResponse(200).send_in_one_call(request.send)
        else:
            await DAVResponse(404).send_in_one_call(request.send)
        return

    async def _do_head(self, path: DAVPath) -> bool:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-48
    9.6.  DELETE Requirements
    
       DELETE is defined in [RFC2616], Section 9.7, to "delete the resource
       identified by the Request-URI".  However, WebDAV changes some DELETE
       handling requirements.
    
       A server processing a successful DELETE request:
    
          MUST destroy locks rooted on the deleted resource
    
          MUST remove the mapping from the Request-URI to any resource.
    
       Thus, after a successful DELETE operation (and in the absence of
       other actions), a subsequent GET/HEAD/PROPFIND request to the target
       Request-URI MUST return 404 (Not Found).
    
    9.6.1.  DELETE for Collections
    
       The DELETE method on a collection MUST act as if a "Depth: infinity"
       header was used on it.  A client MUST NOT submit a Depth header with
       a DELETE on a collection with any value but infinity.
    
       DELETE instructs that the collection specified in the Request-URI and
       all resources identified by its internal member URLs are to be
       deleted.
    
       If any resource identified by a member URL cannot be deleted, then
       all of the member's ancestors MUST NOT be deleted, so as to maintain
       URL namespace consistency.
    
       Any headers included with DELETE MUST be applied in processing every
       resource to be deleted.
    
       When the DELETE method has completed processing, it MUST result in a
       consistent URL namespace.
    
       If an error occurs deleting a member resource (a resource other than
       the resource identified in the Request-URI), then the response can be
       a 207 (Multi-Status).  Multi-Status is used here to indicate which
       internal resources could NOT be deleted, including an error code,
       which should help the client understand which resources caused the
       failure.  For example, the Multi-Status body could include a response
       with status 423 (Locked) if an internal resource was locked.
    
       The server MAY return a 4xx status response, rather than a 207, if
       the request failed completely.
    
       424 (Failed Dependency) status codes SHOULD NOT be in the 207 (Multi-
       Status) response for DELETE.  They can be safely left out because the
       client will know that the ancestors of a resource could not be
       deleted when the client receives an error for the ancestor's progeny.
       Additionally, 204 (No Content) errors SHOULD NOT be returned in the
       207 (Multi-Status).  The reason for this prohibition is that 204 (No
       Content) is the default success code.
    
    https://tools.ietf.org/html/rfc2616#section-9.7
    9.7 DELETE
    
       The DELETE method requests that the origin server delete the resource
       identified by the Request-URI. This method MAY be overridden by human
       intervention (or other means) on the origin server. The client cannot
       be guaranteed that the operation has been carried out, even if the
       status code returned from the origin server indicates that the action
       has been completed successfully. However, the server SHOULD NOT
       indicate success unless, at the time the response is given, it
       intends to delete the resource or move it to an inaccessible
       location.
    
       A successful response SHOULD be 200 (OK) if the response includes an
       entity describing the status, 202 (Accepted) if the action has not
       yet been enacted, or 204 (No Content) if the action has been enacted
       but the response does not include an entity.
    
       If the request passes through a cache and the Request-URI identifies
       one or more currently cached entities, those entries SHOULD be
       treated as stale. Responses to this method are not cacheable.
    """

    async def do_delete(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:
        if await self.lock.is_locking(request.src_path, request.lock_token):
            await DAVResponse(423).send_in_one_call(request.send)
            return False

        http_status = await self._do_delete(passport.src_path)
        if http_status == 204:
            await self.lock.release(request.lock_token)

        await DAVResponse(http_status).send_in_one_call(request.send)
        return True

    async def _do_delete(self, path: DAVPath) -> int:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-50
    9.7.  PUT Requirements
    
    9.7.1.  PUT for Non-Collection Resources
    
       A PUT performed on an existing resource replaces the GET response
       entity of the resource.  Properties defined on the resource may be
       recomputed during PUT processing but are not otherwise affected.  For
       example, if a server recognizes the content type of the request body,
       it may be able to automatically extract information that could be
       profitably exposed as properties_list.
    
       A PUT that would result in the creation of a resource without an
       appropriately scoped parent collection MUST fail with a 409
       (Conflict).
    
       A PUT request allows a client to indicate what media type an entity
       body has, and whether it should change if overwritten.  Thus, a
       client SHOULD provide a Content-Type for a new resource if any is
       known.  If the client does not provide a Content-Type for a new
       resource, the server MAY create a resource with no Content-Type
       assigned, or it MAY attempt to assign a Content-Type.
    
       Note that although a recipient ought generally to treat metadata
       supplied with an HTTP request as authoritative, in practice there's
       no guarantee that a server will accept client-supplied metadata
       (e.g., any request header beginning with "Content-").  Many servers
       do not allow configuring the Content-Type on a per-resource basis in
       the first place.  Thus, clients can't always rely on the ability to
       directly influence the content type by including a Content-Type
       request header.
    
    9.7.2.  PUT for Collections
    
       This specification does not define the behavior of the PUT method for
       existing collections.  A PUT request to an existing collection MAY be
       treated as an error (405 Method Not Allowed).
    
       The MKCOL method is defined to create collections.
    """

    async def do_put(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:
        if await self.lock.is_locking(request.src_path, request.lock_token):
            await DAVResponse(423).send_in_one_call(request.send)
            return False

        if not request.lock_token_is_parsed_success:
            await DAVResponse(412).send_in_one_call(request.send)
            return False

        http_status = await self._do_put(
            passport.src_path, request.receive
        )
        await DAVResponse(http_status).send_in_one_call(request.send)
        return True

    async def _do_put(self, path: DAVPath, receive: Callable) -> int:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-51
    9.8.  COPY Method
    9.8.5.  Status Codes
    
       In addition to the general status codes possible, the following
       status codes have specific applicability to COPY:
    
       201 (Created) - The source resource was successfully copied.  The
       COPY operation resulted in the creation of a new resource.
    
       204 (No Content) - The source resource was successfully copied to a
       preexisting destination resource.
    
       207 (Multi-Status) - Multiple resources were to be affected by the
       COPY, but errors on some of them prevented the operation from taking
       place.  Specific error messages, together with the most appropriate
       of the source and destination URLs, appear in the body of the multi-
       status response.  For example, if a destination resource was locked
       and could not be overwritten, then the destination resource URL
       appears with the 423 (Locked) status.
    
       403 (Forbidden) - The operation is forbidden.  A special case for
       COPY could be that the source and destination resources are the same
       resource.
    
       409 (Conflict) - A resource cannot be created at the destination
       until one or more intermediate collections have been created.  The
       server MUST NOT create those intermediate collections automatically.
    
       412 (Precondition Failed) - A precondition header check failed, e.g.,
       the Overwrite header is "F" and the destination URL is already mapped
       to a resource.
    
       423 (Locked) - The destination resource, or resource within the
       destination collection, was locked.  This response SHOULD contain the
       'lock-token-submitted' precondition element.
    
       502 (Bad Gateway) - This may occur when the destination is on another
       server, repository, or URL namespace.  Either the source namespace
       does not support copying to the destination namespace, or the
       destination namespace refuses to accept the resource.  The client may
       wish to try GET/PUT and PROPFIND/PROPPATCH instead.
    
       507 (Insufficient Storage) - The destination resource does not have
       sufficient space to record the state of the resource after the
       execution of this method.
    """

    async def do_copy(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:
        if not request.dst_path.startswith(passport.src_prefix):
            # Do not support between DAVProvider instance
            await DAVResponse(400).send_in_one_call(request.send)
            return False

        if request.depth is None:
            await DAVResponse(403).send_in_one_call(request.send)
            return False

        if await self.lock.is_locking(request.dst_path, request.lock_token):
            await DAVResponse(423).send_in_one_call(request.send)
            return False

        http_status = await self._do_copy(
            passport.src_path, passport.dst_path,
            request.depth, request.overwrite
        )
        await DAVResponse(http_status).send_in_one_call(request.send)
        return True

    async def _do_copy(
        self, src_path: DAVPath, dst_path: DAVPath,
        depth: int, overwrite: bool = False
    ) -> int:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-56
    9.9.  MOVE Method
    9.9.4.  Status Codes
    
       In addition to the general status codes possible, the following
       status codes have specific applicability to MOVE:
    
       201 (Created) - The source resource was successfully moved, and a new
       URL mapping was created at the destination.
    
       204 (No Content) - The source resource was successfully moved to a
       URL that was already mapped.
    
       207 (Multi-Status) - Multiple resources were to be affected by the
       MOVE, but errors on some of them prevented the operation from taking
       place.  Specific error messages, together with the most appropriate
       of the source and destination URLs, appear in the body of the multi-
       status response.  For example, if a source resource was locked and
       could not be moved, then the source resource URL appears with the 423
       (Locked) status.
    
       403 (Forbidden) - Among many possible reasons for forbidding a MOVE
       operation, this status code is recommended for use when the source
       and destination resources are the same.
    
       409 (Conflict) - A resource cannot be created at the destination
       until one or more intermediate collections have been created.  The
       server MUST NOT create those intermediate collections automatically.
       Or, the server was unable to preserve the behavior of the live
       properties_list and still move the resource to the destination (see
       'preserved-live-properties_list' postcondition).
    
       412 (Precondition Failed) - A condition header failed.  Specific to
       MOVE, this could mean that the Overwrite header is "F" and the
       destination URL is already mapped to a resource.
    
       423 (Locked) - The source or the destination resource, the source or
       destination resource parent, or some resource within the source or
       destination collection, was locked.  This response SHOULD contain the
       'lock-token-submitted' precondition element.
    
       502 (Bad Gateway) - This may occur when the destination is on another
       server and the destination server refuses to accept the resource.
       This could also occur when the destination is on another sub-section
       of the same server namespace.
    """

    async def do_move(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:
        if not request.dst_path.startswith(passport.src_prefix):
            # Do not support between DAVProvider instance
            await DAVResponse(400).send_in_one_call(request.send)
            return False

        if await self.lock.is_locking(request.src_path):
            await DAVResponse(423).send_in_one_call(request.send)
            return False
        if await self.lock.is_locking(request.dst_path):
            await DAVResponse(423).send_in_one_call(request.send)
            return False

        http_status = await self._do_move(
            passport.src_path, passport.dst_path, request.overwrite
        )
        await DAVResponse(http_status).send_in_one_call(request.send)
        return True

    async def _do_move(
        self, src_path: DAVPath, dst_path: DAVPath, overwrite: bool = False
    ) -> int:
        raise NotImplementedError

    """
    https://tools.ietf.org/html/rfc4918#page-61
    9.10.  LOCK Method
    9.10.6.  LOCK Responses
    
       In addition to the general status codes possible, the following
       status codes have specific applicability to LOCK:
    
       200 (OK) - The LOCK request succeeded and the value of the DAV:
       lockdiscovery property is included in the response body.
    
       201 (Created) - The LOCK request was to an unmapped URL, the request
       succeeded and resulted in the creation of a new resource, and the
       value of the DAV:lockdiscovery property is included in the response
       body.

       409 (Conflict) - A resource cannot be created at the destination
       until one or more intermediate collections have been created.  The
       server MUST NOT create those intermediate collections automatically.
    
       423 (Locked), potentially with 'no-conflicting-lock' precondition
       code - There is already a lock on the resource that is not compatible
       with the requested lock (see lock compatibility table above).
    
       412 (Precondition Failed), with 'lock-token-matches-request-uri'
       precondition code - The LOCK request was made with an If header,
       indicating that the client wishes to refresh the given lock.
       However, the Request-URI did not fall within the scope of the lock
       identified by the token.  The lock may have a scope that does not
       include the Request-URI, or the lock could have disappeared, or the
       token may be invalid.       
    """

    async def do_lock(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:
        # TODO
        if not request.body_is_parsed_success or not request.lock_token_is_parsed_success:
            await DAVResponse(400).send_in_one_call(request.send)
            return False
        elif request.lock_token:
            # refresh
            lock_info = await self.lock.refresh(request.lock_token)
        else:
            # new
            lock_info = await self.lock.new(request)
            if lock_info is None:
                await DAVResponse(423).send_in_one_call(request.send)
                return False

        data = self._create_lock_response(lock_info)
        response = DAVResponse(status=200, message=data, headers=[
            (b'Lock-Token', bytes(
                'opaquelocktoken:{}'.format(lock_info.token),
                encoding='utf-8'
            )),
        ])
        await response.send_in_one_call(request.send)
        return True

    def _create_lock_response(self, lock_info: DAVLockInfo) -> bytes:
        lock_discovery = self._create_data_lock_discovery(lock_info)
        data = {
            'D:prop': {
                '@xmlns:D': 'DAV:',
                'D:lockdiscovery': lock_discovery,
            }
        }
        return xmltodict.unparse(
            data, short_empty_elements=True
        ).replace('\n', '').encode('utf-8')

    """
    https://tools.ietf.org/html/rfc4918#page-68
    9.11.  UNLOCK Method
    9.11.1.  Status Codes
    
       In addition to the general status codes possible, the following
       status codes have specific applicability to UNLOCK:
    
       204 (No Content) - Normal success response (rather than 200 OK, since
       200 OK would imply a response body, and an UNLOCK success response
       does not normally contain a body).
    
       400 (Bad Request) - No lock token was provided.
    
       403 (Forbidden) - The currently authenticated principal does not have
       permission to remove the lock.
    
       409 (Conflict), with 'lock-token-matches-request-uri' precondition -
       The resource was not locked, or the request was made to a Request-URI
       that was not within the scope of the lock.    
    """

    async def do_unlock(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:
        if request.lock_token is None:
            await DAVResponse(409).send_in_one_call(request.send)
            return False

        sucess = await self.lock.release(request.lock_token)
        if sucess:
            await DAVResponse(204).send_in_one_call(request.send)
            return True

        await DAVResponse(400).send_in_one_call(request.send)
        return False

    async def get_options(
        self, request: DAVRequest, passport: DAVPassport
    ) -> bool:  # TODO

        await DAVResponse(status=200, headers=[
            (
                b'Allow',
                bytes(','.join(DAV_METHODS), encoding='utf-8')
            ),
            (b'DAV', b'1, 2'),
        ]).send_in_one_call(request.send)

        return True
