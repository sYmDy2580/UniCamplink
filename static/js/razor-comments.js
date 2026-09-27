"use strict";

/*
============================================================
    UNICAMPLINK RAZOR COMMENTS
    Shared comment/reply engine for Feed + Profile
============================================================
*/

const razorCsrfToken =
    document.querySelector(
        'input[name="csrf_token"]'
    )?.value || "";


/* ============================================================
   ROBUST API RESPONSE HANDLER
============================================================ */

async function razorParseApiResponse(response) {

    const contentType =
        response.headers.get("content-type") || "";

    if (
        contentType
            .toLowerCase()
            .includes("application/json")
    ) {

        let data;

        try {

            data = await response.json();

        } catch (error) {

            console.error(
                "Invalid JSON response:",
                error
            );

            throw new Error(
                `The server returned invalid JSON (${response.status}).`
            );
        }

        if (!response.ok) {

            throw new Error(
                data?.error ||
                data?.message ||
                `Request failed (${response.status}).`
            );
        }

        if (
            data &&
            data.success === false
        ) {

            throw new Error(
                data.error ||
                data.message ||
                "The request could not be completed."
            );
        }

        return data;
    }

    let responseText = "";

    try {

        responseText =
            await response.text();

    } catch (error) {

        console.error(
            "Unable to read server response:",
            error
        );
    }

    if (
        response.status === 401 ||
        response.redirected
    ) {

        throw new Error(
            "Your session may have expired. Please log in again."
        );
    }

    if (response.status === 403) {

        throw new Error(
            "This action was blocked. Your session may have expired or the request was rejected."
        );
    }

    if (response.status === 404) {

        throw new Error(
            "The requested post or comment could not be found."
        );
    }

    if (response.status === 413) {

        throw new Error(
            "The request is too large."
        );
    }

    if (response.status >= 500) {

        throw new Error(
            "Something went wrong on the server. Please try again."
        );
    }

    const cleanText =
        responseText
            .replace(/<[^>]*>/g, " ")
            .replace(/\s+/g, " ")
            .trim();

    if (
        cleanText &&
        cleanText.length <= 200
    ) {

        throw new Error(cleanText);
    }

    throw new Error(
        `Request failed (${response.status}).`
    );
}


/* ============================================================
   TOGGLE COMMENTS
============================================================ */

function toggleComments(
    postId,
    focusInput = true
) {

    const comments =
        document.getElementById(
            `comments-${postId}`
        );

    if (!comments) {
        return;
    }

    const isVisible =
        comments.classList.contains(
            "visible"
        );

    if (isVisible) {

        comments.classList.remove(
            "visible"
        );

        return;
    }

    comments.classList.add(
        "visible"
    );

    loadComments(postId);

    if (focusInput) {

        const input =
            comments.querySelector(
                ".comment-form input[name='content']"
            );

        if (input) {

            setTimeout(
                function () {

                    try {

                        input.focus({
                            preventScroll: true
                        });

                    } catch (error) {

                        input.focus();
                    }

                },
                80
            );
        }
    }
}


function focusComment(postId) {

    toggleComments(
        postId,
        true
    );
}


/* ============================================================
   COMMENTS — AJAX
============================================================ */

document.addEventListener(
    "submit",
    async function(event) {

        const form =
            event.target.closest(
                ".comment-form"
            );

        if (!form) {
            return;
        }

        event.preventDefault();

        const input =
            form.querySelector(
                "input[name='content']"
            );

        const button =
            form.querySelector(
                "button[type='submit']"
            );

        const postId =
            form.dataset.postId;

        if (
            !input ||
            !button ||
            !postId
        ) {
            return;
        }

        const content =
            input.value.trim();

        if (!content) {
            return;
        }

        if (button.disabled) {
            return;
        }

        button.disabled = true;

        const parentCommentId =
            input.dataset.parentCommentId || "";

        const formData =
            new FormData(form);

        if (parentCommentId) {

            formData.set(
                "parent_comment_id",
                parentCommentId
            );

        } else {

            formData.delete(
                "parent_comment_id"
            );
        }

        try {

            const response =
                await fetch(
                    form.action,
                    {
                        method: "POST",

                        headers: {
                            "X-CSRFToken":
                                razorCsrfToken,

                            "X-Requested-With":
                                "XMLHttpRequest",

                            "Accept":
                                "application/json"
                        },

                        credentials:
                            "same-origin",

                        body:
                            formData
                    }
                );

            const data =
                await razorParseApiResponse(
                    response
                );

            const commentsList =
                document.querySelector(
                    `#comments-${postId} .comments-list`
                );

            if (
                commentsList &&
                data.comment
            ) {

                addCommentToList(
                    commentsList,
                    data.comment
                );
            }

            const post =
                document.getElementById(
                    `post-${postId}`
                );

            if (post) {

                const count =
                    post.querySelector(
                        ".comment-count"
                    );

                if (count) {

                    count.textContent =
                        data.comment_count;
                }
            }

            input.value = "";

            cancelReply(input);

        } catch (error) {

            console.error(
                "Comment error:",
                error
            );

            alert(
                error.message ||
                "Unable to add comment."
            );

        } finally {

            button.disabled = false;
        }
    }
);


/* ============================================================
   ADD COMMENT / REPLY
============================================================ */

function addCommentToList(
    commentsList,
    comment
) {

    if (
        !commentsList ||
        !comment ||
        !comment.id
    ) {
        return;
    }

    const commentId =
        String(comment.id);

    const existing =
        commentsList.querySelector(
            `[data-comment-id="${CSS.escape(commentId)}"]`
        );

    if (existing) {
        return;
    }

    const commentElement =
        document.createElement(
            "div"
        );

    commentElement.className =
        "razor-comment";

    commentElement.dataset.commentId =
        commentId;

    commentElement.dataset.parentCommentId =
        comment.parent_comment_id
            ? String(comment.parent_comment_id)
            : "";

    const avatarContainer =
        document.createElement(
            "div"
        );

    avatarContainer.className =
        "comment-avatar";

    const avatarLink =
        document.createElement(
            "a"
        );

    avatarLink.href =
        `/profile/${comment.user_id}`;

    avatarLink.className =
        "comment-avatar-link";

    if (comment.profile_picture) {

        const image =
            document.createElement(
                "img"
            );

        image.src =
            `/static/uploads/${encodeURIComponent(
                comment.profile_picture
            )}`;

        image.alt = "";

        image.className =
            "comment-avatar-image";

        image.addEventListener(
            "error",
            function() {

                this.style.display =
                    "none";

                const placeholder =
                    document.createElement(
                        "div"
                    );

                placeholder.className =
                    "comment-avatar-placeholder";

                placeholder.textContent =
                    "👤";

                avatarLink.appendChild(
                    placeholder
                );

            },
            {
                once: true
            }
        );

        avatarLink.appendChild(
            image
        );

    } else {

        const placeholder =
            document.createElement(
                "div"
            );

        placeholder.className =
            "comment-avatar-placeholder";

        placeholder.textContent =
            "👤";

        avatarLink.appendChild(
            placeholder
        );
    }

    avatarContainer.appendChild(
        avatarLink
    );

    const body =
        document.createElement(
            "div"
        );

    body.className =
        "comment-body";

    const authorLink =
        document.createElement(
            "a"
        );

    authorLink.href =
        `/profile/${comment.user_id}`;

    authorLink.className =
        "comment-author-link";

    authorLink.title =
        "View profile";

    const author =
        document.createElement(
            "strong"
        );

    author.textContent =
        comment.author_name ||
        "UniCamplink User";

    authorLink.appendChild(
        author
    );

    body.appendChild(
        authorLink
    );

    const bubble =
        document.createElement(
            "div"
        );

    bubble.className =
        "comment-bubble";

    bubble.textContent =
        comment.content || "";

    body.appendChild(
        bubble
    );

    const actions =
        document.createElement(
            "div"
        );

    actions.className =
        "comment-actions";

    const replyButton =
        document.createElement(
            "button"
        );

    replyButton.type =
        "button";

    replyButton.className =
        "comment-reply-btn";

    replyButton.textContent =
        "Reply";

    replyButton.addEventListener(
        "click",
        function() {

            prepareReply(
                commentId
            );
        }
    );

    actions.appendChild(
        replyButton
    );

    body.appendChild(
        actions
    );

    commentElement.appendChild(
        avatarContainer
    );

    commentElement.appendChild(
        body
    );

    if (
        !comment.parent_comment_id
    ) {

        commentsList.appendChild(
            commentElement
        );

        return;
    }

    const parentId =
        String(
            comment.parent_comment_id
        );

    const parentComment =
        commentsList.querySelector(
            `[data-comment-id="${CSS.escape(parentId)}"]`
        );

    if (!parentComment) {

        commentsList.appendChild(
            commentElement
        );

        return;
    }

    let repliesContainer =
        parentComment.querySelector(
            ":scope > .comment-replies"
        );

    if (!repliesContainer) {

        repliesContainer =
            document.createElement(
                "div"
            );

        repliesContainer.className =
            "comment-replies";

        parentComment.appendChild(
            repliesContainer
        );
    }

    repliesContainer.appendChild(
        commentElement
    );
}


/* ============================================================
   LOAD COMMENTS
============================================================ */

async function loadComments(postId) {

    const commentsList =
        document.querySelector(
            `#comments-${postId} .comments-list`
        );

    if (!commentsList) {
        return;
    }

    if (
        commentsList.dataset.loaded ===
        "true"
    ) {
        return;
    }

    if (
        commentsList.dataset.loading ===
        "true"
    ) {
        return;
    }

    commentsList.dataset.loading =
        "true";

    try {

        const response =
            await fetch(
                `/comments/${postId}`,
                {
                    method: "GET",

                    headers: {
                        "X-Requested-With":
                            "XMLHttpRequest",

                        "Accept":
                            "application/json"
                    },

                    credentials:
                        "same-origin"
                }
            );

        const data =
            await razorParseApiResponse(
                response
            );

        if (
            !Array.isArray(
                data.comments
            )
        ) {

            throw new Error(
                "The server returned an invalid comments response."
            );
        }

        commentsList.dataset.loaded =
            "true";

        commentsList.replaceChildren();

        const topLevelComments =
            data.comments.filter(
                comment =>
                    !comment.parent_comment_id
            );

        topLevelComments.forEach(
            comment => {

                addCommentToList(
                    commentsList,
                    comment
                );
            }
        );

        const replies =
            data.comments.filter(
                comment =>
                    comment.parent_comment_id
            );

        replies.forEach(
            comment => {

                addCommentToList(
                    commentsList,
                    comment
                );
            }
        );

    } catch (error) {

        delete commentsList.dataset.loaded;

        console.error(
            "Comment loading error:",
            error
        );

    } finally {

        delete commentsList.dataset.loading;
    }
}


/* ============================================================
   PREPARE REPLY
============================================================ */

function prepareReply(commentId) {

    const comment =
        document.querySelector(
            `[data-comment-id="${CSS.escape(
                String(commentId)
            )}"]`
        );

    if (!comment) {
        return;
    }

    const post =
        comment.closest(
            ".razor-post"
        );

    if (!post) {
        return;
    }

    const form =
        post.querySelector(
            ".comment-form"
        );

    if (!form) {
        return;
    }

    const input =
        form.querySelector(
            "input[name='content']"
        );

    if (!input) {
        return;
    }

    input.dataset.parentCommentId =
        String(commentId);

    input.placeholder =
        "Reply to this comment...";

    let cancelButton =
        form.querySelector(
            ".cancel-reply-btn"
        );

    if (!cancelButton) {

        cancelButton =
            document.createElement(
                "button"
            );

        cancelButton.type =
            "button";

        cancelButton.className =
            "cancel-reply-btn";

        cancelButton.textContent =
            "Cancel reply";

        cancelButton.addEventListener(
            "click",
            function() {

                cancelReply(
                    input
                );
            }
        );

        form.appendChild(
            cancelButton
        );
    }

    cancelButton.style.display =
        "inline-block";

    try {

        input.scrollIntoView({
            behavior: "smooth",
            block: "center"
        });

    } catch (error) {

        input.scrollIntoView();
    }

    setTimeout(
        function() {

            input.focus();

        },
        350
    );
}


/* ============================================================
   CANCEL REPLY
============================================================ */

function cancelReply(input) {

    if (!input) {
        return;
    }

    delete input.dataset.parentCommentId;

    input.placeholder =
        "Write a comment...";

    const form =
        input.closest(
            ".comment-form"
        );

    if (!form) {
        return;
    }

    const cancelButton =
        form.querySelector(
            ".cancel-reply-btn"
        );

    if (cancelButton) {

        cancelButton.style.display =
            "none";
    }
}
